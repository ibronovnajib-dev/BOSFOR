from __future__ import annotations

import sqlite3

PHASE2_DDL = '''
CREATE TABLE IF NOT EXISTS os_orders (
    id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    created_by TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK(order_type IN ('delivery','pickup','dinein','pos_dinein')),
    table_id TEXT,
    state TEXT NOT NULL DEFAULT 'open',
    subtotal INTEGER NOT NULL DEFAULT 0,
    discount_total INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    closed_at INTEGER,
    reopened_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_os_orders_state_created ON os_orders(state, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_os_orders_table_state ON os_orders(table_id, state);

CREATE TABLE IF NOT EXISTS os_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES os_orders(id) ON DELETE CASCADE,
    dish_id TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK(qty > 0),
    unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
    name_ru TEXT NOT NULL,
    name_tj TEXT NOT NULL,
    modifiers_json TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    sent_qty INTEGER NOT NULL DEFAULT 0 CHECK(sent_qty >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','void')),
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_os_items_order ON os_order_items(order_id, id);

CREATE TABLE IF NOT EXISTS os_order_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES os_orders(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('percent','fixed')),
    value INTEGER NOT NULL CHECK(value > 0),
    amount INTEGER NOT NULL CHECK(amount >= 0),
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS os_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES os_orders(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    method TEXT NOT NULL CHECK(method IN ('cash','card','qr','wallet')),
    amount INTEGER NOT NULL CHECK(amount > 0),
    direction TEXT NOT NULL CHECK(direction IN ('payment','refund')),
    parent_payment_id INTEGER REFERENCES os_payments(id),
    reason TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_os_payments_order ON os_payments(order_id, id);

CREATE TABLE IF NOT EXISTS os_table_state (
    table_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'free',
    version INTEGER NOT NULL DEFAULT 1,
    active_order_id TEXT REFERENCES os_orders(id),
    seating_id INTEGER,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS os_seatings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id TEXT NOT NULL,
    order_id TEXT REFERENCES os_orders(id),
    reservation_id TEXT,
    actor_id TEXT NOT NULL,
    seated_at INTEGER NOT NULL,
    ended_at INTEGER
);

CREATE TABLE IF NOT EXISTS os_kitchen_stations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target_minutes INTEGER NOT NULL DEFAULT 15,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS os_dish_station (
    dish_id TEXT PRIMARY KEY,
    station_id TEXT NOT NULL REFERENCES os_kitchen_stations(id)
);
CREATE TABLE IF NOT EXISTS os_dish_availability (
    dish_id TEXT PRIMARY KEY,
    available INTEGER NOT NULL DEFAULT 1,
    reason TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL DEFAULT 0,
    actor_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS os_kitchen_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES os_orders(id) ON DELETE CASCADE,
    station_id TEXT NOT NULL REFERENCES os_kitchen_stations(id),
    state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','preparing','ready','recalled','cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    sent_at INTEGER NOT NULL,
    started_at INTEGER,
    ready_at INTEGER,
    target_minutes INTEGER NOT NULL DEFAULT 15,
    actor_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS os_kitchen_ticket_items (
    ticket_id INTEGER NOT NULL REFERENCES os_kitchen_tickets(id) ON DELETE CASCADE,
    order_item_id INTEGER NOT NULL REFERENCES os_order_items(id),
    qty INTEGER NOT NULL CHECK(qty > 0),
    PRIMARY KEY(ticket_id, order_item_id)
);
'''


def ensure_phase2_schema(con: sqlite3.Connection) -> None:
    # Domain operations call this defensively. Never use executescript once the
    # schema exists because sqlite3.executescript() implicitly commits an active
    # transaction, defeating BEGIN IMMEDIATE concurrency guarantees.
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='os_orders'").fetchone():
        return
    con.executescript(PHASE2_DDL)
    con.execute("INSERT OR IGNORE INTO os_kitchen_stations(id,name,target_minutes,active,sort_order) VALUES('default','Основная кухня',15,1,0)")

PHASE3_DDL = '''
CREATE TABLE IF NOT EXISTS inventory_units (
    code TEXT PRIMARY KEY,
    dimension TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unit_conversions (
    from_unit TEXT NOT NULL REFERENCES inventory_units(code),
    to_unit TEXT NOT NULL REFERENCES inventory_units(code),
    factor TEXT NOT NULL,
    dimension TEXT NOT NULL,
    PRIMARY KEY(from_unit,to_unit)
);
CREATE TABLE IF NOT EXISTS inventory_items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_unit TEXT NOT NULL REFERENCES inventory_units(code),
    reorder_point TEXT NOT NULL DEFAULT '0',
    target_stock TEXT NOT NULL DEFAULT '0',
    weighted_avg_cost TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES inventory_items(id),
    qty_base TEXT NOT NULL,
    movement_type TEXT NOT NULL,
    unit_cost TEXT,
    ref_type TEXT NOT NULL DEFAULT '',
    ref_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_movements_item ON stock_movements(item_id,id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_ref ON stock_movements(ref_type,ref_id);
CREATE TRIGGER IF NOT EXISTS stock_movements_no_update
BEFORE UPDATE ON stock_movements BEGIN SELECT RAISE(ABORT,'stock movements are immutable'); END;
CREATE TRIGGER IF NOT EXISTS stock_movements_no_delete
BEFORE DELETE ON stock_movements BEGIN SELECT RAISE(ABORT,'stock movements are immutable'); END;

CREATE TABLE IF NOT EXISTS recipes (
    dish_id TEXT PRIMARY KEY,
    updated_at INTEGER NOT NULL,
    updated_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recipe_components (
    dish_id TEXT NOT NULL REFERENCES recipes(dish_id) ON DELETE CASCADE,
    item_id TEXT NOT NULL REFERENCES inventory_items(id),
    qty_base TEXT NOT NULL,
    base_unit TEXT NOT NULL REFERENCES inventory_units(code),
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(dish_id,item_id)
);
CREATE INDEX IF NOT EXISTS idx_recipe_components_item ON recipe_components(item_id);

CREATE TABLE IF NOT EXISTS waste_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES inventory_items(id),
    qty_base TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    movement_id INTEGER NOT NULL UNIQUE REFERENCES stock_movements(id),
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_count_lines (
    count_id INTEGER NOT NULL REFERENCES stock_counts(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL REFERENCES inventory_items(id),
    counted_qty_base TEXT NOT NULL,
    system_qty_base TEXT NOT NULL,
    variance_base TEXT NOT NULL,
    movement_id INTEGER REFERENCES stock_movements(id),
    PRIMARY KEY(count_id,item_id)
);
CREATE TRIGGER IF NOT EXISTS waste_events_no_update
BEFORE UPDATE ON waste_events BEGIN SELECT RAISE(ABORT,'waste events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS waste_events_no_delete
BEFORE DELETE ON waste_events BEGIN SELECT RAISE(ABORT,'waste events are immutable'); END;

CREATE TABLE IF NOT EXISTS suppliers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS supplier_items (
    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    item_id TEXT NOT NULL REFERENCES inventory_items(id),
    supplier_sku TEXT NOT NULL DEFAULT '',
    last_cost TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(supplier_id,item_id)
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    status TEXT NOT NULL CHECK(status IN ('draft','approved','partial','received','cancelled')),
    note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    approved_by TEXT,
    approved_at INTEGER
);
CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id TEXT NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL REFERENCES inventory_items(id),
    ordered_qty_base TEXT NOT NULL,
    base_unit TEXT NOT NULL REFERENCES inventory_units(code),
    unit_cost TEXT NOT NULL,
    received_qty_base TEXT NOT NULL DEFAULT '0'
);
CREATE INDEX IF NOT EXISTS idx_po_lines_po ON purchase_order_lines(po_id,id);
CREATE TABLE IF NOT EXISTS goods_receipts (
    id TEXT PRIMARY KEY,
    po_id TEXT NOT NULL REFERENCES purchase_orders(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    actor_id TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS goods_receipt_lines (
    receipt_id TEXT NOT NULL REFERENCES goods_receipts(id) ON DELETE CASCADE,
    po_line_id INTEGER NOT NULL REFERENCES purchase_order_lines(id),
    qty_base TEXT NOT NULL,
    unit_cost TEXT NOT NULL,
    movement_id INTEGER NOT NULL UNIQUE REFERENCES stock_movements(id),
    PRIMARY KEY(receipt_id,po_line_id)
);
'''


def _seed_phase3_units(con: sqlite3.Connection) -> None:
    # Seed only when needed so defensive schema checks remain read-only on the
    # hot path and do not acquire write locks inside inventory transactions.
    if con.execute("SELECT 1 FROM inventory_units WHERE code='kg'").fetchone():
        return
    con.executemany(
        'INSERT OR IGNORE INTO inventory_units(code,dimension) VALUES(?,?)',
        [('g','mass'),('kg','mass'),('ml','volume'),('l','volume'),('pcs','count')],
    )
    con.executemany(
        'INSERT OR IGNORE INTO unit_conversions(from_unit,to_unit,factor,dimension) VALUES(?,?,?,?)',
        [('kg','g','1000','mass'),('l','ml','1000','volume')],
    )


def ensure_phase3_schema(con: sqlite3.Connection) -> None:
    required = {'inventory_items', 'stock_movements', 'recipes', 'recipe_components', 'waste_events', 'stock_counts', 'stock_count_lines', 'suppliers', 'purchase_orders', 'purchase_order_lines', 'goods_receipts', 'goods_receipt_lines'}
    present = {row['name'] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'") if row['name'] in required}
    if present != required:
        if con.in_transaction:
            raise RuntimeError('phase 3 schema must be initialized before opening a transaction')
        con.executescript(PHASE3_DDL)
    _seed_phase3_units(con)

PHASE4_DDL = '''
CREATE TABLE IF NOT EXISTS os_reservation_tables (
    reservation_id TEXT PRIMARY KEY,
    table_id TEXT NOT NULL,
    assigned_by TEXT NOT NULL,
    assigned_at INTEGER NOT NULL,
    seated_order_id TEXT REFERENCES os_orders(id),
    released_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_reservation_table_active ON os_reservation_tables(table_id,released_at);

CREATE TABLE IF NOT EXISTS os_waitlist (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    guests INTEGER NOT NULL CHECK(guests > 0),
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','notified','seated','cancelled','no_show')),
    created_by TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    seated_at INTEGER,
    seated_table_id TEXT,
    order_id TEXT REFERENCES os_orders(id),
    closed_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_waitlist_status_created ON os_waitlist(status,created_at);

CREATE TABLE IF NOT EXISTS os_staff_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id TEXT NOT NULL,
    start_at INTEGER NOT NULL,
    end_at INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_staff_shifts_staff_start ON os_staff_shifts(staff_id,start_at);

CREATE TABLE IF NOT EXISTS os_clock_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('in','out','correction')),
    occurred_at INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    ref_event_id INTEGER REFERENCES os_clock_events(id),
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clock_events_staff_id ON os_clock_events(staff_id,id);
CREATE TRIGGER IF NOT EXISTS os_clock_events_no_update
BEFORE UPDATE ON os_clock_events BEGIN SELECT RAISE(ABORT,'clock events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS os_clock_events_no_delete
BEFORE DELETE ON os_clock_events BEGIN SELECT RAISE(ABORT,'clock events are immutable'); END;

CREATE TABLE IF NOT EXISTS os_cash_sessions (
    id TEXT PRIMARY KEY,
    cashier_id TEXT NOT NULL,
    opening_cash INTEGER NOT NULL CHECK(opening_cash >= 0),
    opened_at INTEGER NOT NULL,
    opened_by TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cash_sessions_cashier_opened ON os_cash_sessions(cashier_id,opened_at);
CREATE TABLE IF NOT EXISTS os_cash_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES os_cash_sessions(id),
    actor_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('cash_in','cash_out')),
    amount INTEGER NOT NULL CHECK(amount > 0),
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS os_cash_closes (
    session_id TEXT PRIMARY KEY REFERENCES os_cash_sessions(id),
    closed_by TEXT NOT NULL,
    closed_at INTEGER NOT NULL,
    expected_cash INTEGER NOT NULL,
    counted_cash INTEGER NOT NULL CHECK(counted_cash >= 0),
    variance INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS os_cash_adjustments_no_update
BEFORE UPDATE ON os_cash_adjustments BEGIN SELECT RAISE(ABORT,'cash adjustments are immutable'); END;
CREATE TRIGGER IF NOT EXISTS os_cash_adjustments_no_delete
BEFORE DELETE ON os_cash_adjustments BEGIN SELECT RAISE(ABORT,'cash adjustments are immutable'); END;
CREATE TRIGGER IF NOT EXISTS os_cash_closes_no_update
BEFORE UPDATE ON os_cash_closes BEGIN SELECT RAISE(ABORT,'cash close is immutable'); END;
CREATE TRIGGER IF NOT EXISTS os_cash_closes_no_delete
BEFORE DELETE ON os_cash_closes BEGIN SELECT RAISE(ABORT,'cash close is immutable'); END;

CREATE TABLE IF NOT EXISTS os_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount > 0),
    category TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expenses_created ON os_expenses(created_at,id);
CREATE TRIGGER IF NOT EXISTS os_expenses_no_update
BEFORE UPDATE ON os_expenses BEGIN SELECT RAISE(ABORT,'expenses are immutable'); END;
CREATE TRIGGER IF NOT EXISTS os_expenses_no_delete
BEFORE DELETE ON os_expenses BEGIN SELECT RAISE(ABORT,'expenses are immutable'); END;
'''


def ensure_phase4_schema(con: sqlite3.Connection) -> None:
    required = {'os_reservation_tables', 'os_waitlist', 'os_staff_shifts', 'os_clock_events', 'os_cash_sessions', 'os_cash_adjustments', 'os_cash_closes', 'os_expenses'}
    present = {row['name'] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'") if row['name'] in required}
    if present == required:
        return
    if con.in_transaction:
        raise RuntimeError('phase 4 schema must be initialized before opening a transaction')
    con.executescript(PHASE4_DDL)

PHASE5_DDL = '''
CREATE TABLE IF NOT EXISTS crm_customers (
    phone TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    visits INTEGER NOT NULL DEFAULT 0,
    lifetime_spend INTEGER NOT NULL DEFAULT 0,
    last_visit_ts INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS crm_customer_tags (
    phone TEXT NOT NULL REFERENCES crm_customers(phone) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(phone,tag)
);
CREATE TABLE IF NOT EXISTS crm_customer_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL REFERENCES crm_customers(phone) ON DELETE CASCADE,
    note TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crm_notes_phone_created ON crm_customer_notes(phone,created_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS crm_loyalty_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL REFERENCES crm_customers(phone) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK(event_type IN ('earn','redeem','reversal')),
    delta INTEGER NOT NULL CHECK(delta != 0),
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    ref_event_id INTEGER REFERENCES crm_loyalty_events(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_loyalty_phone_id ON crm_loyalty_events(phone,id);
CREATE TRIGGER IF NOT EXISTS crm_loyalty_no_update
BEFORE UPDATE ON crm_loyalty_events BEGIN SELECT RAISE(ABORT,'loyalty events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS crm_loyalty_no_delete
BEFORE DELETE ON crm_loyalty_events BEGIN SELECT RAISE(ABORT,'loyalty events are immutable'); END;

CREATE TABLE IF NOT EXISTS delivery_zones (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    fee INTEGER NOT NULL CHECK(fee >= 0),
    min_order INTEGER NOT NULL CHECK(min_order >= 0),
    service_start TEXT NOT NULL,
    service_end TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL,
    updated_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS os_delivery_orders (
    order_id TEXT PRIMARY KEY REFERENCES os_orders(id) ON DELETE CASCADE,
    zone_id TEXT NOT NULL REFERENCES delivery_zones(id),
    zone_name TEXT NOT NULL,
    fee INTEGER NOT NULL,
    min_order INTEGER NOT NULL,
    service_start TEXT NOT NULL,
    service_end TEXT NOT NULL,
    quoted_at INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'quoted' CHECK(state IN ('quoted','assigned','picked_up','delivered','cancelled')),
    courier_id TEXT,
    tracking_token TEXT,
    assigned_at INTEGER,
    picked_up_at INTEGER,
    delivered_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_delivery_state ON os_delivery_orders(state,quoted_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_tracking_token ON os_delivery_orders(tracking_token) WHERE tracking_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS ops_task_templates (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ops_task_template_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, template_id TEXT NOT NULL REFERENCES ops_task_templates(id) ON DELETE CASCADE,
    title TEXT NOT NULL, due_offset_min INTEGER NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ops_checklists (
    id TEXT PRIMARY KEY, template_id TEXT NOT NULL REFERENCES ops_task_templates(id), business_date TEXT NOT NULL, assigned_to TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ops_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, checklist_id TEXT NOT NULL REFERENCES ops_checklists(id) ON DELETE CASCADE, title TEXT NOT NULL,
    assigned_to TEXT NOT NULL DEFAULT '', due_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','in_progress','done','skipped')),
    skip_reason TEXT NOT NULL DEFAULT '', started_at INTEGER, completed_at INTEGER, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ops_tasks_status_due ON ops_tasks(status,due_at);
CREATE TABLE IF NOT EXISTS ops_task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES ops_tasks(id) ON DELETE CASCADE, event_type TEXT NOT NULL, actor_id TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS ops_task_events_no_update BEFORE UPDATE ON ops_task_events BEGIN SELECT RAISE(ABORT,'task events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS ops_task_events_no_delete BEFORE DELETE ON ops_task_events BEGIN SELECT RAISE(ABORT,'task events are immutable'); END;
CREATE TABLE IF NOT EXISTS ops_logbook (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entry TEXT NOT NULL, actor_id TEXT NOT NULL, related_type TEXT NOT NULL DEFAULT '', related_id TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logbook_created ON ops_logbook(created_at DESC,id DESC);
'''


def ensure_phase5_schema(con: sqlite3.Connection) -> None:
    required={'crm_customers','crm_customer_tags','crm_customer_notes','crm_loyalty_events','delivery_zones','os_delivery_orders','ops_task_templates','ops_task_template_items','ops_checklists','ops_tasks','ops_task_events','ops_logbook'}
    present={r['name'] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'") if r['name'] in required}
    needs_base = present != required
    delivery_cols=set()
    if 'os_delivery_orders' in present:
        delivery_cols={r['name'] for r in con.execute('PRAGMA table_info(os_delivery_orders)')}
    needs_tracking = 'os_delivery_orders' in present and 'tracking_token' not in delivery_cols
    if not needs_base and not needs_tracking:
        con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_tracking_token ON os_delivery_orders(tracking_token) WHERE tracking_token IS NOT NULL')
        return
    if con.in_transaction:
        raise RuntimeError('phase 5 schema must be initialized before opening a transaction')
    if needs_base:
        con.executescript(PHASE5_DDL)
    if needs_tracking:
        con.execute('ALTER TABLE os_delivery_orders ADD COLUMN tracking_token TEXT')
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_tracking_token ON os_delivery_orders(tracking_token) WHERE tracking_token IS NOT NULL')

FOUNDATION_DDL = '''
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS staff_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS staff_roles (
    user_id INTEGER PRIMARY KEY REFERENCES staff_users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('owner','manager','cashier','waiter','kitchen','courier'))
);
CREATE TABLE IF NOT EXISTS role_permissions (
    role TEXT NOT NULL,
    permission TEXT NOT NULL,
    PRIMARY KEY(role,permission)
);
CREATE TABLE IF NOT EXISTS staff_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_staff_sessions_user ON staff_sessions(user_id,expires_at);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER REFERENCES staff_users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    reason TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_id,created_at DESC);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'audit events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit events are immutable'); END;
'''

ROLE_PERMISSIONS = {
    'owner': ['*'],
    'manager': ['pos.read','pos.write','floor.write','kitchen.read','inventory.manage','purchasing.manage','staff.schedule','reports.read','crm.manage','delivery.manage','tasks.manage','menu.manage','settings.read'],
    'cashier': ['pos.read','pos.write','payments.write','cash.manage','receipt.read'],
    'waiter': ['pos.read','pos.write','floor.write','reservations.write','crm.service_note'],
    'kitchen': ['kitchen.read','kitchen.write','dish_availability.write'],
    'courier': ['delivery.assigned.read','delivery.assigned.write'],
}

def current_schema_version(con) -> int:
    con.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL)')
    row=con.execute('SELECT COALESCE(MAX(version),0) v FROM schema_migrations').fetchone()
    return int(row['v'] if hasattr(row,'keys') else row[0])

def apply_migrations(con) -> list[int]:
    import time
    applied=[]
    con.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL)')
    if current_schema_version(con) < 1:
        if con.in_transaction: raise RuntimeError('migrations require no active transaction')
        con.executescript(FOUNDATION_DDL)
        for role,perms in ROLE_PERMISSIONS.items():
            for permission in perms:
                con.execute('INSERT OR IGNORE INTO role_permissions(role,permission) VALUES(?,?)',(role,permission))
        con.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,?)',(int(time.time()*1000),))
        applied.append(1)
    return applied
