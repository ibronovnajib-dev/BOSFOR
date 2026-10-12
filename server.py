#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bosfor restaurant web server.

Production-oriented, dependency-free Python server with:
- dedicated public web root (private files are never served);
- SQLite + WAL transactions for concurrent orders/bookings;
- server-side order pricing and input validation;
- rate limiting + payload limits;
- password login, HttpOnly sessions and CSRF protection for admin actions;
- security headers and same-origin API access;
- one-time migration from legacy JSON files.

Run:
    python3 server.py

Optional environment variables:
    PORT=8080
    BOSFOR_ADMIN_PASSWORD='use-a-long-password'
    BOSFOR_HTTPS=1                    # sets Secure cookie when HTTPS terminates here/proxy forwards HTTPS
    BOSFOR_TELEGRAM_BOT_TOKEN='...'
    BOSFOR_TELEGRAM_CHAT_ID='...'
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import hmac
import http.cookies
import http.server
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
from zoneinfo import ZoneInfo
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from bosfor.migrations import ensure_phase2_schema, ensure_phase3_schema, ensure_phase4_schema, ensure_phase5_schema, apply_migrations, current_schema_version
from bosfor.api_pos import handle_pos_action, list_orders as v1_list_orders
from bosfor.api_floor import handle_floor_action, list_floor as v1_list_floor
from bosfor.api_kitchen import handle_kitchen_action, get_tickets as v1_kitchen_tickets
from bosfor.orders import OrderConflict
from bosfor.finance_ledger import LedgerConflict
from bosfor.tables import FloorConflict
from bosfor.kitchen import KitchenConflict
from bosfor.inventory import InventoryConflict
from bosfor.api_inventory import handle_inventory_action, list_items as v1_inventory_items, list_low_stock as v1_low_stock, get_recipe as v1_inventory_recipe
from bosfor.purchasing import PurchasingConflict
from bosfor.api_purchasing import handle_purchasing_action, list_suppliers as v1_suppliers, list_orders as v1_purchase_orders, list_suggestions as v1_reorder_suggestions
from bosfor.reservations import ReservationConflict
from bosfor.staff import StaffConflict
from bosfor.finance import CashConflict
from bosfor.api_reservations import handle_reservation_action, list_reservations as v1_reservations, list_waitlist as v1_waitlist, wait_quote as v1_wait_quote
from bosfor.api_staff import handle_staff_action, list_shifts as v1_staff_shifts, staff_summary as v1_staff_summary
from bosfor.api_finance import handle_finance_action, list_cash_sessions as v1_cash_sessions, list_expenses as v1_expenses, finance_daily as v1_finance_daily
from bosfor.crm import CRMConflict, get_or_create_customer, recompute_customer_metrics, earn_points
from bosfor.delivery import DeliveryConflict, safe_tracking_by_token
from bosfor.tasks import TaskConflict
from bosfor.api_crm import handle_crm_action, get_profile as v1_crm_profile, list_customers as v1_crm_customers
from bosfor.api_delivery import handle_delivery_action, list_zones as v1_delivery_zones, list_deliveries as v1_deliveries
from bosfor.api_tasks import handle_task_action, list_tasks as v1_tasks, list_overdue as v1_overdue_tasks, list_templates as v1_task_templates, list_logbook as v1_logbook
from bosfor.reports import live_dashboard, historical_report, export_csv
from bosfor.diagnostics import diagnose
from bosfor.db import connect as db_connect
from bosfor.auth import bootstrap_owner, authenticate, create_session as auth_create_session, resolve_session as auth_resolve_session, delete_session as auth_delete_session, list_staff as auth_list_staff, create_staff as auth_create_staff, set_role as auth_set_role, set_enabled as auth_set_enabled
from bosfor.audit import record_event as audit_record, list_events as audit_list

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
PRIVATE = ROOT / "private"
LEGACY = PRIVATE / "legacy-json"
DB_PATH = PRIVATE / "bosfor.sqlite3"
ADMIN_FILE = PRIVATE / "admin-password.txt"
PORT = int(os.environ.get("PORT", "8080"))
HTTPS_COOKIE = os.environ.get("BOSFOR_HTTPS", "0").strip().lower() in {"1", "true", "yes", "on"}
MAX_BODY = 96 * 1024
MAX_ASSET_BODY = 3 * 1024 * 1024
SESSION_TTL = 12 * 60 * 60
ORDER_RATE = int(os.environ.get("BOSFOR_ORDER_RATE_PER_MIN", "60"))
BOOKING_RATE = int(os.environ.get("BOSFOR_BOOKING_RATE_PER_MIN", "30"))

mimetypes.add_type("application/manifest+json", ".webmanifest")

DB_INIT_LOCK = threading.Lock()
SESSIONS_LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
SESSIONS: dict[str, dict] = {}
RATE_BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)

NAME_RE = re.compile(r"^[^<>\x00-\x1f]{2,80}$")
DISH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
SAFE_IMG_RE = re.compile(r"^img/[A-Za-z0-9_./-]{1,180}$")
VALID_ORDER_STATUS = {"new", "confirmed", "cooking", "delivery", "done", "cancelled"}
VALID_BOOKING_STATUS = {"new", "confirmed", "cancelled"}
VALID_PAY = {"cash", "card", "qr", "wallet"}
VALID_MODE = {"delivery", "pickup", "dinein"}
VALID_CATS = {"break", "grill", "fast", "sushi", "salad", "drinks"}
RESTAURANT_TZ = ZoneInfo("Asia/Dushanbe")


def now_ms() -> int:
    return int(time.time() * 1000)


def db() -> sqlite3.Connection:
    return db_connect(DB_PATH)


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _admin_password() -> str:
    env = os.environ.get("BOSFOR_ADMIN_PASSWORD", "")
    if env:
        return env
    PRIVATE.mkdir(parents=True, exist_ok=True)
    if ADMIN_FILE.exists():
        return ADMIN_FILE.read_text(encoding="utf-8").strip()
    password = secrets.token_urlsafe(16)
    ADMIN_FILE.write_text(password + "\n", encoding="utf-8")
    try:
        os.chmod(ADMIN_FILE, 0o600)
    except OSError:
        pass
    print("[SECURITY] Generated admin password (first run):", password)
    print("[SECURITY] Stored outside web root at:", ADMIN_FILE)
    print("[SECURITY] Prefer setting BOSFOR_ADMIN_PASSWORD in production.")
    return password


ADMIN_PASSWORD = _admin_password()


def init_db() -> None:
    with DB_INIT_LOCK:
        PRIVATE.mkdir(parents=True, exist_ok=True)
        first = not DB_PATH.exists()
        con = db()
        try:
            con.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS dishes (
                    id TEXT PRIMARY KEY,
                    cat TEXT NOT NULL,
                    img TEXT,
                    price INTEGER NOT NULL CHECK(price >= 0),
                    hot INTEGER NOT NULL DEFAULT 0,
                    ru TEXT NOT NULL,
                    tj TEXT NOT NULL,
                    dru TEXT NOT NULL DEFAULT '',
                    dtj TEXT NOT NULL DEFAULT '',
                    off INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    allergens TEXT NOT NULL DEFAULT '',
                    ingredients TEXT NOT NULL DEFAULT '',
                    modifiers TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    idem_key TEXT UNIQUE,
                    ts INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    addr TEXT NOT NULL DEFAULT '',
                    pay TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    table_no TEXT NOT NULL DEFAULT '',
                    scheduled_for TEXT NOT NULL DEFAULT '',
                    subtotal INTEGER NOT NULL DEFAULT 0,
                    discount INTEGER NOT NULL DEFAULT 0,
                    delivery_fee INTEGER NOT NULL DEFAULT 0,
                    promo_code TEXT NOT NULL DEFAULT '',
                    loyalty_earned INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS order_items (
                    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    dish_id TEXT NOT NULL,
                    q INTEGER NOT NULL,
                    n TEXT NOT NULL,
                    n2 TEXT NOT NULL,
                    p INTEGER NOT NULL,
                    PRIMARY KEY(order_id, dish_id)
                );
                CREATE TABLE IF NOT EXISTS bookings (
                    id TEXT PRIMARY KEY,
                    idem_key TEXT UNIQUE,
                    ts INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    guests TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'new'
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS customers (
                    phone TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    orders_count INTEGER NOT NULL DEFAULT 0,
                    total_spent INTEGER NOT NULL DEFAULT 0,
                    points INTEGER NOT NULL DEFAULT 0,
                    last_order_ts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS promotions (
                    code TEXT PRIMARY KEY,
                    discount_type TEXT NOT NULL CHECK(discount_type IN ('percent','fixed')),
                    value INTEGER NOT NULL CHECK(value > 0),
                    min_total INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    starts_at INTEGER NOT NULL DEFAULT 0,
                    ends_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tables_map (
                    code TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    capacity INTEGER NOT NULL DEFAULT 2,
                    zone TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts DESC);
                CREATE INDEX IF NOT EXISTS idx_bookings_ts ON bookings(ts DESC);
                CREATE INDEX IF NOT EXISTS idx_bookings_slot ON bookings(date, time, status);
                """
            )
            # Forward-compatible schema upgrades for databases created by older builds.
            for ddl in (
                "ALTER TABLE orders ADD COLUMN table_no TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE orders ADD COLUMN scheduled_for TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE orders ADD COLUMN subtotal INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE orders ADD COLUMN discount INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE orders ADD COLUMN delivery_fee INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE orders ADD COLUMN promo_code TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE orders ADD COLUMN loyalty_earned INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE dishes ADD COLUMN allergens TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE dishes ADD COLUMN ingredients TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE dishes ADD COLUMN modifiers TEXT NOT NULL DEFAULT '[]'",
            ):
                try:
                    con.execute(ddl)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            if first:
                migrate_legacy(con)
            ensure_defaults(con)
            ensure_phase2_schema(con)
            ensure_phase3_schema(con)
            ensure_phase4_schema(con)
            ensure_phase5_schema(con)
            apply_migrations(con)
            bootstrap_owner(con, ADMIN_PASSWORD)
        finally:
            con.close()


def ensure_defaults(con: sqlite3.Connection) -> None:
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('ordering','true')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('telegram_bot','')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('telegram_chat','')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('delivery_fee','0')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('min_order','0')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('loyalty_percent','3')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('scheduled_orders','true')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('max_bookings_per_slot','8')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('delivery_zone_note','Доставка по Душанбе. Условия уточняются при подтверждении заказа.')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('opening_time','07:00')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('closing_time','22:30')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('logo_url','img/logo.png')")
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('favicon_url','icons/favicon-64.png')")


def migrate_legacy(con: sqlite3.Connection) -> None:
    dishes = _read_json(LEGACY / "dishes.json", [])
    orders = _read_json(LEGACY / "orders.json", [])
    bookings = _read_json(LEGACY / "bookings.json", [])
    settings = _read_json(LEGACY / "settings.json", {})
    con.execute("BEGIN IMMEDIATE")
    try:
        for i, d in enumerate(dishes if isinstance(dishes, list) else []):
            try:
                con.execute(
                    "INSERT OR IGNORE INTO dishes(id,cat,img,price,hot,ru,tj,dru,dtj,off,sort_order,allergens,ingredients,modifiers) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(d.get("id", "")), str(d.get("cat", "fast")), d.get("img") or None,
                     int(d.get("price", 0)), int(bool(d.get("hot"))), str(d.get("ru", "")),
                     str(d.get("tj", d.get("ru", ""))), str(d.get("dru", "")), str(d.get("dtj", d.get("dru", ""))),
                     int(bool(d.get("off"))), i, str(d.get("allergens", "")), str(d.get("ingredients", "")), str(d.get("modifiers", "[]"))),
                )
            except Exception as exc:
                print("[MIGRATE] skipped dish:", exc)
        for o in orders if isinstance(orders, list) else []:
            try:
                oid = str(o.get("id") or "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", oid):
                    oid = make_id("FF")
                con.execute(
                    "INSERT OR IGNORE INTO orders(id,idem_key,ts,name,phone,mode,addr,pay,total,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (oid, None, int(o.get("ts") or now_ms()), str(o.get("name", "")), str(o.get("phone", "")),
                     str(o.get("mode", "pickup")), str(o.get("addr", "")), str(o.get("pay", "cash")),
                     int(o.get("total", 0)), str(o.get("status", "new"))),
                )
                for it in o.get("items", []) if isinstance(o.get("items"), list) else []:
                    did = str(it.get("id") or "legacy-" + secrets.token_hex(4))
                    con.execute(
                        "INSERT OR IGNORE INTO order_items(order_id,dish_id,q,n,n2,p) VALUES(?,?,?,?,?,?)",
                        (oid, did, max(1, int(it.get("q", 1))), str(it.get("n", "")), str(it.get("n2", it.get("n", ""))), int(it.get("p", 0))),
                    )
            except Exception as exc:
                print("[MIGRATE] skipped order:", exc)
        for b in bookings if isinstance(bookings, list) else []:
            try:
                con.execute(
                    "INSERT OR IGNORE INTO bookings(id,idem_key,ts,name,phone,guests,date,time,note,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (str(b.get("id")) if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(b.get("id") or "")) else make_id("BK"), None, int(b.get("ts") or now_ms()), str(b.get("name", "")),
                     str(b.get("phone", "")), str(b.get("guests", "1–2")), str(b.get("date", "")), str(b.get("time", "")),
                     str(b.get("note", "")), str(b.get("status", "new"))),
                )
            except Exception as exc:
                print("[MIGRATE] skipped booking:", exc)
        if isinstance(settings, dict):
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('ordering',?)", (json.dumps(bool(settings.get("ordering", True))),))
            tg = settings.get("telegram") if isinstance(settings.get("telegram"), dict) else {}
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('telegram_bot',?)", (str(tg.get("bot", "")),))
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('telegram_chat',?)", (str(tg.get("chat", "")),))
        con.commit()
        print(f"[MIGRATE] imported {len(dishes)} dishes, {len(orders)} orders, {len(bookings)} bookings")
    except Exception:
        con.rollback()
        raise


def get_setting(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def ordering_open(con: sqlite3.Connection) -> bool:
    raw = get_setting(con, "ordering", "true")
    try:
        return bool(json.loads(raw))
    except Exception:
        return raw.lower() not in {"0", "false", "off", "no"}


def normalize_phone(value: object) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 9:
        digits = "992" + digits
    if not (len(digits) == 12 and digits.startswith("992")):
        return None
    return "+" + digits


def clean_text(value: object, *, min_len: int = 0, max_len: int = 200) -> str | None:
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(s) < min_len or len(s) > max_len or any(ord(c) < 32 for c in s):
        return None
    return s


def make_id(prefix: str) -> str:
    return f"{prefix}-{dt.datetime.now().strftime('%y%m%d')}-{secrets.token_hex(4).upper()}"


def rate_ok(ip: str, bucket: str, limit: int, window: int) -> bool:
    now = time.monotonic()
    key = (ip, bucket)
    with RATE_LOCK:
        q = RATE_BUCKETS[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        # opportunistic cleanup
        if len(RATE_BUCKETS) > 5000:
            for k in list(RATE_BUCKETS)[:1000]:
                if not RATE_BUCKETS[k] or now - RATE_BUCKETS[k][-1] > 3600:
                    RATE_BUCKETS.pop(k, None)
        return True


def session_create(actor: dict | None = None) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    actor = actor or {"id":"owner","role":"owner","name":"Owner"}
    with SESSIONS_LOCK:
        SESSIONS[token] = {"expires": time.time() + SESSION_TTL, "csrf": csrf, "id": str(actor.get("id","owner")), "role": str(actor.get("role","owner")), "name": str(actor.get("name","Owner"))}
    return token, csrf


def session_get(token: str | None):
    if not token:
        return None
    now = time.time()
    with SESSIONS_LOCK:
        s = SESSIONS.get(token)
        if s:
            if s["expires"] < now:
                SESSIONS.pop(token, None)
                return None
            s["expires"] = now + SESSION_TTL
            return dict(s)
    con=db()
    try:
        return auth_resolve_session(con, token)
    finally:
        con.close()


def session_delete(token: str | None) -> None:
    if token:
        with SESSIONS_LOCK:
            SESSIONS.pop(token, None)
        con=db()
        try: auth_delete_session(con, token)
        finally: con.close()


def telegram_send(text: str) -> None:
    def work():
        con = db()
        try:
            bot = os.environ.get("BOSFOR_TELEGRAM_BOT_TOKEN", "").strip() or get_setting(con, "telegram_bot", "").strip()
            chat = os.environ.get("BOSFOR_TELEGRAM_CHAT_ID", "").strip() or get_setting(con, "telegram_chat", "").strip()
        finally:
            con.close()
        if not bot or not chat:
            return
        try:
            data = json.dumps({"chat_id": chat, "text": text}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{bot}/sendMessage",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=6) as response:
                print("[TG] sent:", response.status)
        except Exception as exc:
            print("[TG] error:", exc)
    threading.Thread(target=work, daemon=True).start()


class BosforHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "Bosfor"
    sys_version = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    @property
    def client_ip(self) -> str:
        # Only trust socket peer by default. Reverse-proxy deployments should rate-limit at the proxy too.
        return self.client_address[0]

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: https:; "
            "connect-src 'self'; frame-src https://maps.google.com https://www.google.com; form-action 'self'"
        )
        if HTTPS_COOKIE:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    def _json(self, obj, code: int = 200, extra_headers: dict | None = None):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self, max_body: int = MAX_BODY):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "invalid content length"
        if n <= 0:
            return {}, None
        if n > max_body:
            return None, "payload too large"
        try:
            raw = self.rfile.read(n)
            obj = json.loads(raw.decode("utf-8"))
            if not isinstance(obj, dict):
                return None, "JSON object required"
            return obj, None
        except Exception:
            return None, "invalid json"

    def _cookies(self) -> http.cookies.SimpleCookie:
        c = http.cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        return c

    def _session_token(self) -> str | None:
        morsel = self._cookies().get("bosfor_session")
        return morsel.value if morsel else None

    def _session(self):
        return session_get(self._session_token())

    def _require_admin(self, *, csrf: bool = False):
        sess = self._session()
        if not sess:
            self._json({"error": "authentication required"}, 401)
            return None
        if sess.get("role", "owner") not in {"owner","manager"}:
            self._json({"error": "permission denied"}, 403)
            return None
        if csrf:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(supplied, sess["csrf"]):
                self._json({"error": "csrf validation failed"}, 403)
                return None
        return sess

    def _v1_error(self, code: str, message: str, status: int):
        return self._json({"ok": False, "error": {"code": code, "message": message}}, status)

    def _require_v1(self, *, csrf: bool = False):
        sess = self._session()
        if not sess:
            self._v1_error("auth_required", "authentication required", 401)
            return None
        if csrf:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(supplied, sess.get("csrf", "")):
                self._v1_error("csrf_failed", "csrf validation failed", 403)
                return None
        return sess

    def _run_v1(self, fn):
        try:
            status, data = fn()
            return self._json({"ok": True, "data": data}, status)
        except PermissionError as exc:
            return self._v1_error("permission_denied", str(exc), 403)
        except (OrderConflict, LedgerConflict, FloorConflict, KitchenConflict, InventoryConflict, PurchasingConflict, ReservationConflict, StaffConflict, CashConflict, CRMConflict, DeliveryConflict, TaskConflict) as exc:
            msg = str(exc) or "conflict"
            status = 404 if "not found" in msg else 409
            return self._v1_error("not_found" if status == 404 else "conflict", msg, status)
        except (ValueError, TypeError) as exc:
            return self._v1_error("validation_error", str(exc) or "invalid request", 422)
        except KeyError:
            return self._v1_error("not_found", "endpoint not found", 404)

    def _cookie_header(self, token: str, max_age: int = SESSION_TTL) -> str:
        parts = [f"bosfor_session={token}", "Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={max_age}"]
        if HTTPS_COOKIE:
            parts.append("Secure")
        return "; ".join(parts)

    def _public_settings(self):
        con = db()
        try:
            bot = os.environ.get("BOSFOR_TELEGRAM_BOT_TOKEN", "").strip() or get_setting(con, "telegram_bot", "").strip()
            chat = os.environ.get("BOSFOR_TELEGRAM_CHAT_ID", "").strip() or get_setting(con, "telegram_chat", "").strip()
            def int_setting(key, default=0):
                try: return max(0, int(get_setting(con, key, str(default))))
                except Exception: return default
            raw_sched = get_setting(con, "scheduled_orders", "true")
            try: sched = bool(json.loads(raw_sched))
            except Exception: sched = raw_sched.lower() not in {"0","false","off","no"}
            out = {
                "ordering": ordering_open(con), "tg_configured": bool(bot and chat),
                "delivery_fee": int_setting("delivery_fee"), "min_order": int_setting("min_order"),
                "loyalty_percent": min(25, int_setting("loyalty_percent", 3)), "scheduled_orders": sched,
                "max_bookings_per_slot": min(100, max(1, int_setting("max_bookings_per_slot", 8))),
                "delivery_zone_note": get_setting(con, "delivery_zone_note", ""),
                "opening_time": get_setting(con, "opening_time", "07:00"),
                "closing_time": get_setting(con, "closing_time", "22:30"),
                "logo_url": get_setting(con, "logo_url", "img/logo.png"),
                "favicon_url": get_setting(con, "favicon_url", "icons/favicon-64.png")
            }
            if self._session():
                out["tg_chat"] = chat
            return out
        finally:
            con.close()

    def do_OPTIONS(self):
        # No cross-origin API. Same-origin browser requests do not require CORS preflight.
        self.send_response(204)
        self.send_header("Allow", "GET, POST, HEAD, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/health":
            try:
                con = db()
                try:
                    con.execute("SELECT 1").fetchone()
                    version = current_schema_version(con)
                finally:
                    con.close()
                return self._json({"ok": True, "db": True, "ts": int(time.time()), "schema_version": version})
            except Exception:
                return self._json({"ok": False, "db": False, "ts": int(time.time()), "schema_version": 0}, 503)
        if path == "/api/dishes":
            con = db()
            try:
                rows = con.execute("""SELECT d.id,d.cat,d.img,d.price,d.hot,d.ru,d.tj,d.dru,d.dtj,
                    CASE WHEN COALESCE(a.available,1)=0 THEN 1 ELSE d.off END AS off,
                    d.allergens,d.ingredients,d.modifiers
                    FROM dishes d LEFT JOIN os_dish_availability a ON a.dish_id=d.id
                    ORDER BY d.sort_order,d.id""").fetchall()
                return self._json([dict(r) for r in rows])
            finally:
                con.close()
        if path == "/api/settings":
            return self._json(self._public_settings())
        if path == "/api/delivery-track":
            token = (query.get("token") or [""])[0].strip()
            if not token or set(query)-{"token"}:
                return self._json({"error":"tracking token required"}, 422)
            if not rate_ok(self.client_ip, "delivery-track", 30, 60):
                return self._json({"error":"too many requests"}, 429, {"Retry-After":"60"})
            con = db()
            try:
                try: data = safe_tracking_by_token(con, token)
                except DeliveryConflict: return self._json({"error":"delivery not found"}, 404)
                return self._json(data)
            finally: con.close()
        if path == "/api/order-track":
            oid = clean_text((query.get("id") or [""])[0], min_len=4, max_len=64)
            phone = normalize_phone((query.get("phone") or [""])[0])
            if not oid or not phone:
                return self._json({"error":"id and phone required"}, 422)
            if not rate_ok(self.client_ip, "track", 30, 60):
                return self._json({"error":"too many requests"}, 429, {"Retry-After":"60"})
            con = db()
            try:
                r = con.execute("SELECT id,ts,mode,total,status,scheduled_for,loyalty_earned FROM orders WHERE id=? AND phone=?", (oid,phone)).fetchone()
                if not r: return self._json({"error":"order not found"},404)
                return self._json(dict(r))
            finally: con.close()
        if path == "/api/tables":
            con=db()
            try:
                if self._session():
                    rows=con.execute("SELECT code,label,capacity,zone,active,sort_order FROM tables_map ORDER BY sort_order,code").fetchall()
                else:
                    rows=con.execute("SELECT code,label,capacity,zone,active,sort_order FROM tables_map WHERE active=1 ORDER BY sort_order,code").fetchall()
                return self._json([dict(r) for r in rows])
            finally: con.close()
        if path == "/api/customers":
            if not self._require_admin(): return
            con=db()
            try:
                rows=con.execute("SELECT phone,name,orders_count,total_spent,points,last_order_ts FROM customers ORDER BY last_order_ts DESC LIMIT 2000").fetchall()
                return self._json([dict(r) for r in rows])
            finally: con.close()
        if path == "/api/promotions":
            if not self._require_admin(): return
            con=db()
            try:
                rows=con.execute("SELECT code,discount_type,value,min_total,active,starts_at,ends_at FROM promotions ORDER BY code").fetchall()
                return self._json([dict(r) for r in rows])
            finally: con.close()
        if path == "/api/admin/session":
            sess = self._session()
            return self._json({"authenticated": bool(sess), "csrf": sess["csrf"] if sess else "", "role": sess.get("role", "") if sess else "", "name": sess.get("name", "") if sess else ""})
        if path == "/api/orders":
            if not self._require_admin():
                return
            con = db()
            try:
                orders = []
                for r in con.execute("SELECT * FROM orders ORDER BY ts DESC LIMIT 2000"):
                    o = dict(r); o.pop("idem_key", None)
                    items = con.execute("SELECT dish_id AS id,q,n,n2,p FROM order_items WHERE order_id=? ORDER BY rowid", (o["id"],)).fetchall()
                    o["items"] = [dict(i) for i in items]
                    orders.append(o)
                return self._json(orders)
            finally:
                con.close()
        if path == "/api/bookings":
            if not self._require_admin():
                return
            con = db()
            try:
                rows = con.execute("SELECT id,ts,name,phone,guests,date,time,note,status FROM bookings ORDER BY ts DESC LIMIT 2000").fetchall()
                return self._json([dict(r) for r in rows])
            finally:
                con.close()
        if path == "/api/admin/v1/pos/orders":
            sess = self._require_v1()
            if not sess: return
            con = db()
            try:
                try: data = v1_list_orders(con, sess)
                except PermissionError as exc: return self._v1_error("permission_denied", str(exc), 403)
                return self._json({"ok": True, "data": data})
            finally: con.close()
        if path == "/api/admin/v1/floor/tables":
            sess = self._require_v1()
            if not sess: return
            con = db()
            try:
                try: data = v1_list_floor(con, sess)
                except PermissionError as exc: return self._v1_error("permission_denied", str(exc), 403)
                return self._json({"ok": True, "data": data})
            finally: con.close()
        if path == "/api/admin/v1/kitchen/tickets":
            sess = self._require_v1()
            if not sess: return
            con = db()
            try:
                try: data = v1_kitchen_tickets(con, sess)
                except PermissionError as exc: return self._v1_error("permission_denied", str(exc), 403)
                return self._json({"ok": True, "data": data})
            finally: con.close()
        if path in {"/api/admin/v1/inventory/items", "/api/admin/v1/inventory/low-stock", "/api/admin/v1/inventory/recipe"}:
            sess = self._require_v1()
            if not sess: return
            con = db()
            try:
                if path.endswith('/items'):
                    return self._run_v1(lambda: (200, v1_inventory_items(con, sess)))
                if path.endswith('/low-stock'):
                    return self._run_v1(lambda: (200, v1_low_stock(con, sess)))
                dish_id=(query.get('dish_id') or [''])[0]
                return self._run_v1(lambda: (200, v1_inventory_recipe(con, dish_id, sess)))
            finally: con.close()
        if path in {"/api/admin/v1/purchasing/suppliers", "/api/admin/v1/purchasing/orders", "/api/admin/v1/purchasing/suggestions"}:
            sess = self._require_v1()
            if not sess: return
            con = db()
            try:
                if path.endswith('/suppliers'):
                    return self._run_v1(lambda: (200, v1_suppliers(con, sess)))
                if path.endswith('/orders'):
                    return self._run_v1(lambda: (200, v1_purchase_orders(con, sess)))
                return self._run_v1(lambda: (200, v1_reorder_suggestions(con, sess)))
            finally: con.close()
        if path.startswith("/api/admin/v1/reservations/"):
            sess = self._require_v1()
            if not sess: return
            con=db()
            try:
                if path.endswith('/list'): return self._run_v1(lambda:(200,v1_reservations(con,sess)))
                if path.endswith('/waitlist'): return self._run_v1(lambda:(200,v1_waitlist(con,sess)))
                if path.endswith('/quote'):
                    guests=(query.get('guests') or ['0'])[0]
                    return self._run_v1(lambda:(200,v1_wait_quote(con,guests,sess)))
                return self._v1_error('not_found','endpoint not found',404)
            finally: con.close()
        if path.startswith("/api/admin/v1/staff/"):
            sess=self._require_v1()
            if not sess: return
            con=db()
            try:
                if path.endswith('/shifts'):
                    staff_id=(query.get('staff_id') or [''])[0]
                    return self._run_v1(lambda:(200,v1_staff_shifts(con,sess,staff_id)))
                if path.endswith('/summary'):
                    staff_id=(query.get('staff_id') or [sess.get('id','')])[0]; start=(query.get('start_at') or ['0'])[0]; end=(query.get('end_at') or [str(int(time.time()*1000))])[0]
                    return self._run_v1(lambda:(200,v1_staff_summary(con,sess,staff_id,start,end)))
                return self._v1_error('not_found','endpoint not found',404)
            finally: con.close()
        if path.startswith("/api/admin/v1/finance/"):
            sess=self._require_v1()
            if not sess: return
            con=db()
            try:
                if path.endswith('/sessions'): return self._run_v1(lambda:(200,v1_cash_sessions(con,sess)))
                if path.endswith('/expenses'): return self._run_v1(lambda:(200,v1_expenses(con,sess)))
                if path.endswith('/daily'):
                    date=(query.get('date') or [dt.datetime.now(RESTAURANT_TZ).date().isoformat()])[0]
                    return self._run_v1(lambda:(200,v1_finance_daily(con,sess,date)))
                return self._v1_error('not_found','endpoint not found',404)
            finally: con.close()
        if path.startswith("/api/admin/v1/crm/"):
            sess=self._require_v1()
            if not sess: return
            con=db()
            try:
                if path.endswith('/profile'):
                    phone=(query.get('phone') or [''])[0]
                    return self._run_v1(lambda:(200,v1_crm_profile(con,phone,sess)))
                if path.endswith('/list') or path.endswith('/customers'): return self._run_v1(lambda:(200,v1_crm_customers(con,sess)))
                return self._v1_error('not_found','endpoint not found',404)
            finally: con.close()
        if path.startswith("/api/admin/v1/delivery/"):
            sess=self._require_v1()
            if not sess: return
            con=db()
            try:
                if path.endswith('/zones'): return self._run_v1(lambda:(200,v1_delivery_zones(con,sess)))
                if path.endswith('/orders') or path.endswith('/list'): return self._run_v1(lambda:(200,v1_deliveries(con,sess)))
                return self._v1_error('not_found','endpoint not found',404)
            finally: con.close()
        if path.startswith("/api/admin/v1/tasks/"):
            sess=self._require_v1()
            if not sess: return
            con=db()
            try:
                if path.endswith('/list'): return self._run_v1(lambda:(200,v1_tasks(con,sess)))
                if path.endswith('/overdue'): return self._run_v1(lambda:(200,v1_overdue_tasks(con,sess)))
                if path.endswith('/templates'): return self._run_v1(lambda:(200,v1_task_templates(con,sess)))
                if path.endswith('/logbook'): return self._run_v1(lambda:(200,v1_logbook(con,sess)))
                return self._v1_error('not_found','endpoint not found',404)
            finally: con.close()
        if path == "/api/admin/v1/diagnostics":
            sess=self._require_v1()
            if not sess: return
            if sess.get('role')!='owner': return self._v1_error('permission_denied','permission denied',403)
            return self._json({"ok":True,"data":diagnose(DB_PATH,PUBLIC,PRIVATE)})
        if path == "/api/admin/v1/me":
            sess=self._require_v1()
            if not sess: return
            data={k:sess.get(k) for k in ('id','username','name','role','permissions') if k in sess}
            return self._json({"ok":True,"data":data})
        if path == "/api/admin/v1/users":
            sess=self._require_v1()
            if not sess: return
            if sess.get('role')!='owner': return self._v1_error('permission_denied','permission denied',403)
            con=db()
            try: return self._run_v1(lambda:(200,auth_list_staff(con,sess)))
            finally: con.close()
        if path == "/api/admin/v1/audit":
            sess=self._require_v1()
            if not sess: return
            if sess.get('role')!='owner': return self._v1_error('permission_denied','permission denied',403)
            con=db()
            try: return self._json({"ok":True,"data":audit_list(con,limit=500)})
            finally: con.close()
        if path.startswith("/api/admin/v1/reports/"):
            sess=self._require_v1()
            if not sess: return
            if sess.get('role') not in {'owner','manager'}:
                return self._v1_error('permission_denied','permission denied',403)
            con=db()
            try:
                if path.endswith('/live'):
                    return self._run_v1(lambda:(200,live_dashboard(con)))
                if path.endswith('/historical'):
                    date_from=(query.get('from') or [''])[0]; date_to=(query.get('to') or [''])[0]
                    return self._run_v1(lambda:(200,historical_report(con,date_from,date_to)))
                if path.endswith('/csv'):
                    date_from=(query.get('from') or [''])[0]; date_to=(query.get('to') or [''])[0]
                    report=historical_report(con,date_from,date_to)
                    text=export_csv('daily',report['days']).encode('utf-8-sig')
                    self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Disposition','attachment; filename="bosfor-report.csv"');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(text)));self.end_headers();self.wfile.write(text);return
                return self._v1_error('not_found','endpoint not found',404)
            finally: con.close()
        if path == "/api/table-qr.svg":
            if not self._require_admin():
                return
            table_code = clean_text((query.get("table") or [""])[0], min_len=1, max_len=16)
            if not table_code or not re.fullmatch(r"[A-Za-zА-Яа-я0-9_-]{1,16}", table_code):
                return self._json({"error":"invalid table"}, 422)
            base = clean_text((query.get("base") or [""])[0], min_len=8, max_len=180) or ""
            if not re.match(r"^https?://[^/\s]+(?:/[^\s]*)?$", base):
                host = self.headers.get("Host", f"localhost:{PORT}")
                proto = "https" if HTTPS_COOKIE else "http"
                base = f"{proto}://{host}"
            svg = self._qr_svg(table_code, base)
            if svg is None:
                return self._json({"error":"QR generator dependency is missing. Install qrcode."}, 500)
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(svg)))
            self.end_headers()
            self.wfile.write(svg)
            return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/") and path != "/api/admin/logout":
            ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                if path.startswith("/api/admin/v1/"):
                    return self._v1_error("unsupported_media_type", "application/json required", 415)
                return self._json({"error": "application/json required"}, 415)
        payload, error = self._body(MAX_ASSET_BODY if path == "/api/assets" else MAX_BODY)
        if error:
            return self._json({"error": error}, 413 if error == "payload too large" else 400)

        if path == "/api/admin/login":
            if not rate_ok(self.client_ip, "login", 10, 15 * 60):
                return self._json({"error": "too many attempts"}, 429, {"Retry-After": "900"})
            username = str(payload.get("username", "") or "owner").strip() or "owner"
            password = str(payload.get("password", ""))
            con=db()
            try:
                principal=authenticate(con,username,password)
                if not principal:
                    audit_record(con,actor_id=None,action='login_failed',entity_type='auth',reason='invalid credentials',metadata={'username':username,'ip':self.client_ip})
                    time.sleep(0.15)
                    return self._json({"error": "invalid credentials"}, 401)
                sess=auth_create_session(con,int(principal['id']),SESSION_TTL)
                audit_record(con,actor_id=principal['id'],action='login_success',entity_type='auth',entity_id=principal['id'],metadata={'username':principal.get('username','')})
                return self._json({"ok": True, "csrf": sess['csrf'], "role":principal['role'], "name":principal['name']}, 200, {"Set-Cookie": self._cookie_header(sess['token'])})
            finally:
                con.close()

        if path == "/api/admin/logout":
            current=self._session(); token=self._session_token()
            if current:
                con=db()
                try: audit_record(con,actor_id=current.get('id'),action='logout',entity_type='auth',entity_id=current.get('id'),metadata={})
                finally: con.close()
            session_delete(token)
            return self._json({"ok": True}, 200, {"Set-Cookie": self._cookie_header("deleted", 0)})

        if path == "/api/order":
            if not rate_ok(self.client_ip, "order", ORDER_RATE, 60):
                return self._json({"error": "too many orders; try again shortly"}, 429, {"Retry-After": "60"})
            return self._create_order(payload)

        if path == "/api/booking":
            if not rate_ok(self.client_ip, "booking", BOOKING_RATE, 60):
                return self._json({"error": "too many booking requests; try again shortly"}, 429, {"Retry-After": "60"})
            return self._create_booking(payload)

        if path.startswith("/api/admin/v1/users/"):
            sess=self._require_v1(csrf=True)
            if not sess: return
            if sess.get('role')!='owner': return self._v1_error('permission_denied','permission denied',403)
            con=db()
            try:
                action=path.rsplit('/',1)[-1]
                if action=='create':
                    data=auth_create_staff(con,payload.get('username'),payload.get('password'),payload.get('display_name'),payload.get('role'),sess)
                    audit_record(con,actor_id=sess.get('id'),action='staff_created',entity_type='staff',entity_id=data.get('id'),metadata={'role':data.get('role'),'username':data.get('username')})
                    return self._json({"ok":True,"data":data},201)
                if action=='role':
                    data=auth_set_role(con,payload.get('user_id'),payload.get('role'),sess)
                    audit_record(con,actor_id=sess.get('id'),action='staff_role_changed',entity_type='staff',entity_id=payload.get('user_id'),metadata={'role':payload.get('role')})
                    return self._json({"ok":True,"data":data})
                if action=='enabled':
                    data=auth_set_enabled(con,payload.get('user_id'),bool(payload.get('enabled')),sess)
                    audit_record(con,actor_id=sess.get('id'),action='staff_enabled_changed',entity_type='staff',entity_id=payload.get('user_id'),metadata={'enabled':bool(payload.get('enabled'))})
                    return self._json({"ok":True,"data":data})
                return self._v1_error('not_found','endpoint not found',404)
            except PermissionError as exc: return self._v1_error('permission_denied',str(exc),403)
            except (ValueError,TypeError) as exc: return self._v1_error('validation_error',str(exc),422)
            finally: con.close()

        if path.startswith("/api/admin/v1/pos/") or path.startswith("/api/admin/v1/floor/") or path.startswith("/api/admin/v1/kitchen/") or path.startswith("/api/admin/v1/inventory/") or path.startswith("/api/admin/v1/purchasing/") or path.startswith("/api/admin/v1/reservations/") or path.startswith("/api/admin/v1/staff/") or path.startswith("/api/admin/v1/finance/") or path.startswith("/api/admin/v1/crm/") or path.startswith("/api/admin/v1/delivery/") or path.startswith("/api/admin/v1/tasks/"):
            sess = self._require_v1(csrf=True)
            if not sess: return
            con = db()
            try:
                action = path.rsplit("/", 1)[-1]
                if path.startswith("/api/admin/v1/pos/"):
                    return self._run_v1(lambda: handle_pos_action(con, action, payload, sess, self.headers.get("X-Idempotency-Key", "")))
                if path.startswith("/api/admin/v1/floor/"):
                    return self._run_v1(lambda: handle_floor_action(con, action, payload, sess))
                if path.startswith("/api/admin/v1/kitchen/"):
                    return self._run_v1(lambda: handle_kitchen_action(con, action, payload, sess))
                if path.startswith("/api/admin/v1/inventory/"):
                    return self._run_v1(lambda: handle_inventory_action(con, action, payload, sess))
                if path.startswith("/api/admin/v1/purchasing/"):
                    return self._run_v1(lambda: handle_purchasing_action(con, action, payload, sess, self.headers.get("X-Idempotency-Key", "")))
                if path.startswith("/api/admin/v1/reservations/"):
                    return self._run_v1(lambda: handle_reservation_action(con, action, payload, sess))
                if path.startswith("/api/admin/v1/staff/"):
                    return self._run_v1(lambda: handle_staff_action(con, action, payload, sess))
                if path.startswith("/api/admin/v1/finance/"):
                    return self._run_v1(lambda: handle_finance_action(con, action, payload, sess))
                if path.startswith("/api/admin/v1/crm/"):
                    return self._run_v1(lambda: handle_crm_action(con, action, payload, sess, self.headers.get("X-Idempotency-Key", "")))
                if path.startswith("/api/admin/v1/delivery/"):
                    return self._run_v1(lambda: handle_delivery_action(con, action, payload, sess))
                return self._run_v1(lambda: handle_task_action(con, action, payload, sess))
            finally:
                con.close()

        if path in {"/api/status", "/api/dishes", "/api/settings", "/api/promotions", "/api/tables", "/api/assets", "/api/telegram/test", "/api/clear"}:
            if not self._require_admin(csrf=True):
                return
            if path == "/api/status":
                return self._admin_status(payload)
            if path == "/api/dishes":
                return self._admin_dishes(payload)
            if path == "/api/settings":
                return self._admin_settings(payload)
            if path == "/api/promotions":
                return self._admin_promotions(payload)
            if path == "/api/tables":
                return self._admin_tables(payload)
            if path == "/api/assets":
                return self._admin_assets(payload)
            if path == "/api/telegram/test":
                cfg = self._public_settings()
                if not cfg["tg_configured"]:
                    return self._json({"ok": False, "hint": "Telegram bot token or chat_id is not configured"}, 400)
                telegram_send("✅ «БОСФОР» — Telegram notifications are working.")
                return self._json({"ok": True})
            if path == "/api/clear":
                return self._admin_clear(payload)

        return self._json({"error": "not found"}, 404)

    def _create_order(self, p: dict):
        name = clean_text(p.get("name"), min_len=2, max_len=80)
        phone = normalize_phone(p.get("phone"))
        mode = str(p.get("mode", ""))
        pay = str(p.get("pay", ""))
        addr = clean_text(p.get("addr"), min_len=0, max_len=180)
        table_no = clean_text(p.get("table_no"), min_len=0, max_len=16) or ""
        scheduled_for = clean_text(p.get("scheduled_for"), min_len=0, max_len=32) or ""
        promo_code = re.sub(r"[^A-Z0-9_-]", "", str(p.get("promo_code", "")).upper())[:32]
        items = p.get("items")
        idem = clean_text(self.headers.get("X-Idempotency-Key", ""), max_len=80) or None
        if not name or not NAME_RE.match(name):
            return self._json({"error": "invalid name"}, 422)
        if not phone:
            return self._json({"error": "invalid phone"}, 422)
        if mode not in VALID_MODE:
            return self._json({"error": "invalid mode"}, 422)
        if pay not in VALID_PAY:
            return self._json({"error": "invalid payment method"}, 422)
        if mode == "delivery" and (not addr or len(addr) < 5):
            return self._json({"error": "delivery address required"}, 422)
        if mode == "dinein" and (not table_no or not re.fullmatch(r"[A-Za-zА-Яа-я0-9_-]{1,16}", table_no)):
            return self._json({"error": "table number required"}, 422)
        if scheduled_for:
            try:
                sv = dt.datetime.fromisoformat(scheduled_for)
                now = dt.datetime.now(RESTAURANT_TZ).replace(tzinfo=None)
                if sv < now + dt.timedelta(minutes=20) or sv > now + dt.timedelta(days=7): raise ValueError
                if not (7 <= sv.hour <= 22): raise ValueError
            except Exception:
                return self._json({"error": "invalid scheduled time"}, 422)
        if not isinstance(items, list) or not 1 <= len(items) <= 30:
            return self._json({"error": "invalid items"}, 422)

        requested: dict[str, int] = {}
        expected_prices: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                return self._json({"error": "invalid item"}, 422)
            dish_id = str(item.get("id", ""))
            try:
                qty = int(item.get("qty", item.get("q", 0)))
            except Exception:
                qty = 0
            if not DISH_ID_RE.fullmatch(dish_id) or not 1 <= qty <= 20:
                return self._json({"error": "invalid item"}, 422)
            requested[dish_id] = requested.get(dish_id, 0) + qty
            if "expected_price" in item:
                try:
                    expected_prices[dish_id] = int(item.get("expected_price"))
                except Exception:
                    return self._json({"error": "invalid expected price"}, 422)
            if requested[dish_id] > 20:
                return self._json({"error": "quantity too large"}, 422)

        con = db()
        try:
            if not ordering_open(con):
                return self._json({"error": "ordering paused"}, 409)
            if mode == "dinein":
                active_tables = con.execute("SELECT COUNT(*) AS c FROM tables_map WHERE active=1").fetchone()["c"]
                if active_tables:
                    ok_table = con.execute("SELECT 1 FROM tables_map WHERE code=? AND active=1", (table_no,)).fetchone()
                    if not ok_table:
                        return self._json({"error":"unknown table number"}, 422)
            if scheduled_for:
                raw_sched=get_setting(con,"scheduled_orders","true")
                try: sched_ok=bool(json.loads(raw_sched))
                except Exception: sched_ok=raw_sched.lower() not in {"0","false","off","no"}
                if not sched_ok: return self._json({"error":"scheduled ordering disabled"},409)
            if idem:
                old = con.execute("SELECT id,total,ts FROM orders WHERE idem_key=?", (idem,)).fetchone()
                if old:
                    return self._json({"ok": True, "id": old["id"], "total": old["total"], "ts": old["ts"], "duplicate": True})
            placeholders = ",".join("?" for _ in requested)
            rows = con.execute(
                f"SELECT id,price,ru,tj,off FROM dishes WHERE id IN ({placeholders})",
                tuple(requested.keys()),
            ).fetchall()
            catalog = {r["id"]: r for r in rows}
            unavailable = {r["dish_id"] for r in con.execute(
                f"SELECT dish_id FROM os_dish_availability WHERE available=0 AND dish_id IN ({placeholders})", tuple(requested.keys())
            ).fetchall()}
            if len(catalog) != len(requested) or unavailable or any(catalog[k]["off"] for k in requested if k in catalog):
                return self._json({"error": "menu changed; refresh and try again"}, 409)
            if any(k in expected_prices and expected_prices[k] != int(catalog[k]["price"]) for k in requested):
                return self._json({"error": "menu changed; refresh and try again"}, 409)
            subtotal = sum(int(catalog[k]["price"]) * q for k, q in requested.items())
            if subtotal <= 0 or subtotal > 100000:
                return self._json({"error": "invalid total"}, 422)
            try: min_order = max(0, int(get_setting(con, "min_order", "0")))
            except Exception: min_order = 0
            if mode == "delivery" and subtotal < min_order:
                return self._json({"error":"minimum order not reached","minimum":min_order}, 422)
            discount = 0
            if promo_code:
                pr = con.execute("SELECT * FROM promotions WHERE code=? AND active=1", (promo_code,)).fetchone()
                nowv = now_ms()
                if not pr or (pr["starts_at"] and nowv < pr["starts_at"]) or (pr["ends_at"] and nowv > pr["ends_at"]) or subtotal < pr["min_total"]:
                    return self._json({"error":"invalid promo code"}, 422)
                discount = (subtotal * int(pr["value"]) // 100) if pr["discount_type"] == "percent" else int(pr["value"])
                discount = max(0, min(discount, subtotal))
            try: delivery_fee = max(0, int(get_setting(con, "delivery_fee", "0"))) if mode == "delivery" else 0
            except Exception: delivery_fee = 0
            total = subtotal - discount + delivery_fee
            try: loyalty_pct = min(25, max(0, int(get_setting(con, "loyalty_percent", "3"))))
            except Exception: loyalty_pct = 3
            loyalty_earned = total * loyalty_pct // 100
            oid = make_id("BO")
            ts = now_ms()
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    "INSERT INTO orders(id,idem_key,ts,name,phone,mode,addr,pay,total,status,table_no,scheduled_for,subtotal,discount,delivery_fee,promo_code,loyalty_earned) VALUES(?,?,?,?,?,?,?,?,?,'new',?,?,?,?,?,?,?)",
                    (oid, idem, ts, name, phone, mode, addr or "", pay, total, table_no, scheduled_for, subtotal, discount, delivery_fee, promo_code, loyalty_earned),
                )
                for dish_id, qty in requested.items():
                    d = catalog[dish_id]
                    con.execute(
                        "INSERT INTO order_items(order_id,dish_id,q,n,n2,p) VALUES(?,?,?,?,?,?)",
                        (oid, dish_id, qty, d["ru"], d["tj"], int(d["price"])),
                    )
                con.execute("""INSERT INTO customers(phone,name,orders_count,total_spent,points,last_order_ts) VALUES(?,?,1,?,?,?)
                               ON CONFLICT(phone) DO UPDATE SET name=excluded.name, orders_count=customers.orders_count+1,
                               total_spent=customers.total_spent+excluded.total_spent, points=customers.points+excluded.points, last_order_ts=excluded.last_order_ts""",
                            (phone,name,total,loyalty_earned,ts))
                con.commit()
            except Exception:
                con.rollback()
                raise
        except sqlite3.IntegrityError:
            if idem:
                old = con.execute("SELECT id,total,ts FROM orders WHERE idem_key=?", (idem,)).fetchone()
                if old:
                    return self._json({"ok": True, "id": old["id"], "total": old["total"], "ts": old["ts"], "duplicate": True})
            raise
        finally:
            con.close()
        lines = ", ".join(f"{q}x {catalog[k]['ru']}" for k, q in requested.items())
        telegram_send(
            f"🔥 Заказ {oid} · {total} с\n{lines}\n👤 {name} · {phone}\n" +
            (f"🛵 Доставка: {addr}" if mode == "delivery" else (f"🍽 В зале · стол {table_no}" if mode == "dinein" else "🥡 Самовывоз")) +
            (f" · 🕒 {scheduled_for}" if scheduled_for else "") + f" · 💳 {pay}" +
            (f" · 🎟 {promo_code} (-{discount})" if promo_code else "")
        )
        return self._json({"ok": True, "id": oid, "subtotal": subtotal, "discount": discount, "delivery_fee": delivery_fee,
                           "total": total, "loyalty_earned": loyalty_earned, "scheduled_for": scheduled_for, "ts": ts}, 201)

    def _create_booking(self, p: dict):
        name = clean_text(p.get("name"), min_len=2, max_len=80)
        phone = normalize_phone(p.get("phone"))
        guests = clean_text(p.get("guests"), min_len=1, max_len=40)
        date_s = str(p.get("date", ""))
        time_s = str(p.get("time", ""))
        note = clean_text(p.get("note"), max_len=300)
        idem = clean_text(self.headers.get("X-Idempotency-Key", ""), max_len=80) or None
        if not name or not NAME_RE.match(name):
            return self._json({"error": "invalid name"}, 422)
        if not phone:
            return self._json({"error": "invalid phone"}, 422)
        if not guests or not re.fullmatch(r"[0-9–—+\- ]{1,12}|Более 8 · VIP-зал|Зиёда аз 8 · толори VIP", guests):
            return self._json({"error": "invalid guest count"}, 422)
        try:
            date_v = dt.date.fromisoformat(date_s)
        except ValueError:
            return self._json({"error": "invalid date"}, 422)
        today = dt.datetime.now(RESTAURANT_TZ).date()
        if date_v < today or date_v > today + dt.timedelta(days=180):
            return self._json({"error": "booking date out of range"}, 422)
        if not TIME_RE.fullmatch(time_s) or not ("07:00" <= time_s <= "22:30"):
            return self._json({"error": "invalid time"}, 422)

        con = db()
        try:
            if idem:
                old = con.execute("SELECT id,ts FROM bookings WHERE idem_key=?", (idem,)).fetchone()
                if old:
                    return self._json({"ok": True, "id": old["id"], "ts": old["ts"], "duplicate": True})
            # Prevent accidental duplicate submissions from the same phone for the same slot.
            duplicate = con.execute(
                "SELECT id FROM bookings WHERE phone=? AND date=? AND time=? AND status!='cancelled' AND ts>? ORDER BY ts DESC LIMIT 1",
                (phone, date_s, time_s, now_ms() - 5 * 60 * 1000),
            ).fetchone()
            if duplicate:
                return self._json({"error": "similar booking already exists", "id": duplicate["id"]}, 409)
            try:
                max_slot = min(100, max(1, int(get_setting(con, "max_bookings_per_slot", "8"))))
            except Exception:
                max_slot = 8
            taken = con.execute("SELECT COUNT(*) AS c FROM bookings WHERE date=? AND time=? AND status!='cancelled'", (date_s, time_s)).fetchone()["c"]
            if taken >= max_slot:
                return self._json({"error":"booking slot is full"}, 409)
            bid = make_id("BK")
            ts = now_ms()
            con.execute(
                "INSERT INTO bookings(id,idem_key,ts,name,phone,guests,date,time,note,status) VALUES(?,?,?,?,?,?,?,?,?,'new')",
                (bid, idem, ts, name, phone, guests, date_s, time_s, note or ""),
            )
        except sqlite3.IntegrityError:
            if idem:
                old = con.execute("SELECT id,ts FROM bookings WHERE idem_key=?", (idem,)).fetchone()
                if old:
                    return self._json({"ok": True, "id": old["id"], "ts": old["ts"], "duplicate": True})
            raise
        finally:
            con.close()
        telegram_send(f"🍽 Бронь {bid}\n👤 {name} · {phone}\n🗓 {date_s} в {time_s} · 👥 {guests}" + (f"\n💬 {note}" if note else ""))
        return self._json({"ok": True, "id": bid, "ts": ts}, 201)

    def _admin_status(self, p: dict):
        typ, item_id, status = str(p.get("type", "")), str(p.get("id", "")), str(p.get("status", ""))
        if typ == "order":
            table, valid = "orders", VALID_ORDER_STATUS
        elif typ == "booking":
            table, valid = "bookings", VALID_BOOKING_STATUS
        else:
            return self._json({"error": "invalid type"}, 422)
        if status not in valid:
            return self._json({"error": "invalid status"}, 422)
        con = db()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(f"UPDATE {table} SET status=? WHERE id=?", (status, item_id))
            if cur.rowcount == 1 and typ == "order" and status == "done":
                row = con.execute("SELECT id,name,phone,loyalty_earned FROM orders WHERE id=?", (item_id,)).fetchone()
                if row:
                    try:
                        actor = self._session() or {"id":"system","role":"system"}
                        get_or_create_customer(con, row["phone"], row["name"], actor)
                        recompute_customer_metrics(con, row["phone"])
                        points = max(0, int(row["loyalty_earned"] or 0))
                        if points:
                            earn_points(con, row["phone"], points, {"id":"system","role":"system"}, f"legacy-order:{row['id']}:earn", f"order {row['id']}")
                    except CRMConflict:
                        # Historical orders with malformed customer data remain completable; CRM sync is best-effort.
                        pass
            con.commit()
            return self._json({"ok": cur.rowcount == 1}, 200 if cur.rowcount == 1 else 404)
        except Exception:
            if con.in_transaction: con.rollback()
            raise
        finally:
            con.close()

    def _admin_dishes(self, p: dict):
        items = p.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 200:
            return self._json({"error": "items must be a non-empty list"}, 422)
        clean = []
        seen = set()
        for idx, d in enumerate(items):
            if not isinstance(d, dict):
                return self._json({"error": f"invalid dish at {idx}"}, 422)
            dish_id = str(d.get("id", ""))
            cat = str(d.get("cat", ""))
            ru = clean_text(d.get("ru"), min_len=1, max_len=120)
            tj = clean_text(d.get("tj"), min_len=1, max_len=120)
            dru = clean_text(d.get("dru"), max_len=300)
            dtj = clean_text(d.get("dtj"), max_len=300)
            img = clean_text(d.get("img"), max_len=180) or None
            allergens = clean_text(d.get("allergens"), max_len=240) or ""
            ingredients = clean_text(d.get("ingredients"), max_len=500) or ""
            modifiers_raw = d.get("modifiers", "[]")
            try:
                modifiers_obj = json.loads(modifiers_raw) if isinstance(modifiers_raw, str) else modifiers_raw
                if modifiers_obj in (None, ""):
                    modifiers_obj = []
                if not isinstance(modifiers_obj, list) or len(modifiers_obj) > 20:
                    raise ValueError
                safe_mods = []
                for m in modifiers_obj:
                    if not isinstance(m, dict):
                        raise ValueError
                    label = clean_text(m.get("label"), min_len=1, max_len=80)
                    price_delta = int(m.get("price_delta", 0))
                    if not label or not -10000 <= price_delta <= 10000:
                        raise ValueError
                    safe_mods.append({"label": label, "price_delta": price_delta})
                modifiers = json.dumps(safe_mods, ensure_ascii=False, separators=(",",":"))
            except Exception:
                return self._json({"error": f"invalid modifiers at {idx}"}, 422)
            try:
                price = int(d.get("price", -1))
            except Exception:
                price = -1
            if not DISH_ID_RE.fullmatch(dish_id) or dish_id in seen:
                return self._json({"error": f"invalid/duplicate dish id at {idx}"}, 422)
            if cat not in VALID_CATS or ru is None or tj is None or dru is None or dtj is None or not 0 <= price <= 100000:
                return self._json({"error": f"invalid dish fields at {idx}"}, 422)
            if img and (not SAFE_IMG_RE.fullmatch(img) or ".." in img):
                return self._json({"error": f"invalid image path at {idx}"}, 422)
            seen.add(dish_id)
            clean.append((dish_id, cat, img, price, int(bool(d.get("hot"))), ru, tj, dru, dtj, int(bool(d.get("off"))), idx, allergens, ingredients, modifiers))
        con = db()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("DELETE FROM dishes")
                con.executemany(
                    "INSERT INTO dishes(id,cat,img,price,hot,ru,tj,dru,dtj,off,sort_order,allergens,ingredients,modifiers) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    clean,
                )
                actor = self._session() or {}
                audit_record(
                    con,
                    actor_id=actor.get("id"),
                    action="menu_changed",
                    entity_type="menu",
                    metadata={"count": len(clean)},
                )
                con.commit()
            except Exception:
                con.rollback(); raise
        finally:
            con.close()
        return self._json({"ok": True, "count": len(clean)})

    def _admin_settings(self, p: dict):
        con = db()
        try:
            if "ordering" in p:
                con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('ordering',?)", (json.dumps(bool(p["ordering"])),))
            if "tg_bot" in p:
                bot = clean_text(p.get("tg_bot"), max_len=256)
                if bot is None:
                    return self._json({"error": "invalid bot token"}, 422)
                if bot:
                    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('telegram_bot',?)", (bot,))
            for key in ("delivery_fee","min_order","loyalty_percent","max_bookings_per_slot"):
                if key in p:
                    try: val=max(0,int(p[key]))
                    except Exception: return self._json({"error":f"invalid {key}"},422)
                    if key=="loyalty_percent": val=min(25,val)
                    if key=="max_bookings_per_slot": val=min(100,max(1,val))
                    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(key,str(val)))
            for key in ("delivery_zone_note","opening_time","closing_time"):
                if key in p:
                    val = clean_text(p.get(key), max_len=240)
                    if val is None: return self._json({"error":f"invalid {key}"},422)
                    if key in {"opening_time","closing_time"} and not TIME_RE.fullmatch(val):
                        return self._json({"error":f"invalid {key}"},422)
                    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(key,val))
            for key in ("logo_url","favicon_url"):
                if key in p:
                    val = clean_text(p.get(key), min_len=1, max_len=180)
                    if val is None or not SAFE_IMG_RE.fullmatch(val) or ".." in val:
                        return self._json({"error":f"invalid {key}"},422)
                    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(key,val))
            if "scheduled_orders" in p:
                con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('scheduled_orders',?)",(json.dumps(bool(p["scheduled_orders"])),))
            if "tg_chat" in p:
                chat = clean_text(p.get("tg_chat"), max_len=80)
                if chat is None:
                    return self._json({"error": "invalid chat id"}, 422)
                con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('telegram_chat',?)", (chat,))
            actor = self._session() or {}
            audit_record(
                con,
                actor_id=actor.get("id"),
                action="settings_changed",
                entity_type="settings",
                metadata={"keys": sorted(str(k) for k in p.keys())},
            )
            return self._json({"ok": True})
        finally:
            con.close()

    def _admin_promotions(self, p: dict):
        action=str(p.get("action","save"))
        code=re.sub(r"[^A-Z0-9_-]","",str(p.get("code","")).upper())[:32]
        if not code: return self._json({"error":"invalid promo code"},422)
        con=db()
        try:
            if action=="delete":
                con.execute("DELETE FROM promotions WHERE code=?",(code,))
                return self._json({"ok":True})
            typ=str(p.get("discount_type","percent"))
            if typ not in {"percent","fixed"}: return self._json({"error":"invalid discount type"},422)
            try:
                value=int(p.get("value",0)); min_total=max(0,int(p.get("min_total",0)))
                starts_at=max(0,int(p.get("starts_at",0))); ends_at=max(0,int(p.get("ends_at",0)))
            except Exception: return self._json({"error":"invalid promo values"},422)
            if value<=0 or (typ=="percent" and value>100): return self._json({"error":"invalid promo value"},422)
            con.execute("""INSERT INTO promotions(code,discount_type,value,min_total,active,starts_at,ends_at) VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(code) DO UPDATE SET discount_type=excluded.discount_type,value=excluded.value,min_total=excluded.min_total,active=excluded.active,starts_at=excluded.starts_at,ends_at=excluded.ends_at""",
                        (code,typ,value,min_total,int(bool(p.get("active",True))),starts_at,ends_at))
            return self._json({"ok":True})
        finally: con.close()

    def _admin_tables(self, p: dict):
        items = p.get("items")
        if not isinstance(items, list) or len(items) > 200:
            return self._json({"error":"tables must be a list"}, 422)
        clean=[]; seen=set()
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                return self._json({"error":f"invalid table at {idx}"}, 422)
            code = clean_text(item.get("code"), min_len=1, max_len=16)
            label = clean_text(item.get("label"), max_len=80) or code
            zone = clean_text(item.get("zone"), max_len=80) or ""
            try:
                capacity = int(item.get("capacity", 2))
            except Exception:
                capacity = 0
            if not code or not re.fullmatch(r"[A-Za-zА-Яа-я0-9_-]{1,16}", code) or code in seen or not 1 <= capacity <= 30:
                return self._json({"error":f"invalid table fields at {idx}"}, 422)
            seen.add(code)
            clean.append((code,label,capacity,zone,int(bool(item.get("active", True))),idx))
        con=db()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("DELETE FROM tables_map")
                con.executemany("INSERT INTO tables_map(code,label,capacity,zone,active,sort_order) VALUES(?,?,?,?,?,?)", clean)
                con.commit()
            except Exception:
                con.rollback(); raise
        finally:
            con.close()
        return self._json({"ok":True,"count":len(clean)})


    def _admin_assets(self, p: dict):
        kind = str(p.get("kind", "")).strip().lower()
        if kind not in {"logo", "favicon", "dish"}:
            return self._json({"error":"invalid asset kind"}, 422)
        name_hint = re.sub(r"[^A-Za-z0-9_-]", "-", str(p.get("name", kind)).strip())[:50] or kind
        data_url = str(p.get("data", ""))
        m = re.match(r"^data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\r\n]+)$", data_url)
        if not m:
            return self._json({"error":"only PNG, JPG or WEBP image data is allowed"}, 422)
        fmt = "jpg" if m.group(1) in {"jpeg","jpg"} else m.group(1)
        try:
            raw = base64.b64decode(m.group(2), validate=True)
        except Exception:
            return self._json({"error":"invalid base64 image"}, 422)
        if not (128 <= len(raw) <= 2_500_000):
            return self._json({"error":"image size must be between 128 B and 2.5 MB"}, 422)
        if fmt == "png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return self._json({"error":"invalid PNG file"}, 422)
        if fmt == "jpg" and not raw.startswith(b"\xff\xd8\xff"):
            return self._json({"error":"invalid JPG file"}, 422)
        if fmt == "webp" and not (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"):
            return self._json({"error":"invalid WEBP file"}, 422)
        sub = "icons/uploads" if kind == "favicon" else "img/uploads"
        target_dir = PUBLIC / sub
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{kind}-{int(time.time())}-{secrets.token_hex(4)}-{name_hint}.{fmt}"
        target = target_dir / filename
        target.write_bytes(raw)
        try:
            os.chmod(target, 0o644)
        except OSError:
            pass
        url = f"{sub}/{filename}"
        if kind in {"logo", "favicon"}:
            con = db()
            try:
                con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", ("logo_url" if kind == "logo" else "favicon_url", url))
            finally:
                con.close()
        return self._json({"ok": True, "kind": kind, "url": url, "bytes": len(raw)})

    def _qr_svg(self, table_code: str, base_url: str):
        try:
            import qrcode
            import qrcode.image.svg
        except Exception:
            return None
        url = base_url.rstrip("/") + "/?table=" + table_code
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue()

    def _admin_clear(self, p: dict):
        what = str(p.get("what", ""))
        if what not in {"orders", "bookings", "all"}:
            return self._json({"error": "invalid target"}, 422)
        con = db()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                if what in {"orders", "all"}:
                    con.execute("DELETE FROM orders")
                if what in {"bookings", "all"}:
                    con.execute("DELETE FROM bookings")
                con.commit()
            except Exception:
                con.rollback(); raise
        finally:
            con.close()
        return self._json({"ok": True})


def main() -> None:
    init_db()
    readiness=diagnose(DB_PATH,PUBLIC,PRIVATE)
    if not readiness.get("ok"):
        raise RuntimeError("Bosfor startup readiness checks failed; run owner diagnostics for details")
    print("=" * 64)
    print(" BOSFOR server · SQLite/WAL · protected admin · private web root")
    print(f" Site:        http://localhost:{PORT}/")
    print(f" Admin:       http://localhost:{PORT}/admin.html")
    print(f" Database:    {DB_PATH}")
    print(" Admin auth:  BOSFOR_ADMIN_PASSWORD env or generated private password")
    print("=" * 64)
    server = BosforHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
