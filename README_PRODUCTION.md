# BOSFOR Restaurant Platform — Production README

## Current build
This build is a protected restaurant ordering/admin system for **Босфор / Bosfor**.

Main capabilities:
- public restaurant website with menu, cart, delivery/pickup/dine-in and booking;
- admin login with secure session + CSRF;
- SQLite database with WAL/transactions;
- server-side pricing and validation;
- table management for QR/dine-in ordering;
- printable physical QR cards for tables;
- menu editor with import/export JSON, completeness check, allergens, ingredients, modifiers and dish photo upload;
- logo/favicon upload from admin;
- promotions, delivery fee, minimum order, scheduled orders, loyalty and guest CRM;
- Kitchen Display workflow for orders;
- private files and database are not served from the public web root.

## Requirements
Python 3.11+ is recommended.

Install QR generation dependency:

```bash
pip install -r requirements.txt
```

The platform can start without this package, but printable QR SVG generation requires `qrcode`.

## Run locally

```bash
export BOSFOR_ADMIN_PASSWORD='use-a-long-strong-password'
python3 server.py
```

Open:
- Site: `http://localhost:8080/`
- Admin: `http://localhost:8080/admin.html`

If `BOSFOR_ADMIN_PASSWORD` is not set, the server generates a private password file under `private/admin-password.txt`. For production, use an environment variable instead.

## Admin can now manage

### Brand assets
- Upload new logo from admin.
- Upload new favicon from admin.
- Site and admin immediately read `logo_url` and `favicon_url` from settings.
- Only PNG/JPG/WEBP up to 2.5 MB are accepted.

### Physical QR codes
- Add/edit active tables.
- Set real production base URL before printing.
- Print QR cards directly from admin.
- Each QR opens `/?table=<table_code>` and starts dine-in ordering for that table.

### Real menu
- Add/edit/delete dishes.
- Edit ID, category, price, RU/TJ names, RU/TJ descriptions.
- Upload dish photo.
- Add ingredients and allergens.
- Add modifiers JSON.
- Export full menu to JSON.
- Import full menu from JSON.
- Run menu completeness check before handing the system to the owner.

## Production checklist
Before handing the platform to the restaurant as final production:
1. Replace placeholder domain metadata `https://bosfor.example/` with the real domain.
2. Enter the restaurant's real menu, prices, photos, ingredients, allergens and modifiers.
3. Enter the real list of tables and print QR cards after the final domain is live.
4. Set real delivery zone, delivery fee, minimum order and working hours.
5. Configure Telegram bot/chat or SMS provider credentials.
6. Deploy behind HTTPS and a reverse proxy.
7. Run end-to-end tests from real iPhone, Android, PC and tablet.
8. Place server backups outside the public web root.

## Security notes
- Do not expose `private/`, `.git/`, backups or source files through the web server.
- Admin actions require an authenticated session and CSRF token.
- Public orders cannot set price, total, status or order ID.
- Server computes all order totals from the database.
- SQLite database is under `private/` and not served by the static file handler.

## Verified backup and restore

Create an online-consistent SQLite + uploaded-assets backup:

```bash
./backup.sh
```

The archive is written under `private/backups/*.zip`. It contains the SQLite snapshot, only files under public upload directories, and a SHA-256 manifest. It **does not** include `private/admin-password.txt`, environment variables, Telegram credentials, `.env`, or `.git`.

Before restoring, verify and restore into a new empty directory:

```bash
python3 - <<'PY'
from pathlib import Path
from bosfor.backup import verify_backup, restore_to_new_location
archive=Path('private/backups/YOUR_BACKUP.zip')
print(verify_backup(archive))
print(restore_to_new_location(archive, Path('private/restore-check')))
PY
```

Always restore to a new location first, run `PRAGMA integrity_check` / `PRAGMA foreign_key_check`, then perform a controlled cut-over. Never overwrite the live database in place while the server is running.

## Diagnostics and release candidate

Public liveness endpoint (contains no secrets):

```text
GET /api/health
```

Owner-only readiness diagnostics:

```text
GET /api/admin/v1/diagnostics
```

It checks SQLite integrity/foreign keys/WAL/schema version, writable runtime storage, required public assets, Asia/Dushanbe timezone availability and backup age. Secret values are intentionally never returned.

For Windows, `tzdata` is a required dependency and is included in `requirements.txt` so `ZoneInfo("Asia/Dushanbe")` works even when the operating system has no IANA timezone database.

Build a clean production archive:

```bash
python build_release.py
```

The release builder uses an allowlist and excludes runtime database files, `private/`, passwords, `.env`, `.git`, tests, caches and backup contents. Verify the SHA-256 printed by the builder before deployment.
