# Bosfor Restaurant OS — Architecture & Product Design

**Date:** 2026-10-04  
**Project:** Bosfor restaurant platform  
**Design status:** Proposed for implementation after owner review  
**Deployment target:** Single restaurant first; architecture must remain migration-friendly to PostgreSQL/multi-location later.

## 1. Intent and success criteria

Bosfor already has a public menu, cart, delivery/pickup/dine-in ordering, booking, QR tables, admin authentication, menu management, promotions, loyalty/CRM basics, settings, Kitchen Display basics, SQLite transactions, server-side pricing, uploads, and printable QR cards.

The next release turns this into a **Restaurant OS**: one operational system that covers front-of-house, kitchen, inventory, purchasing, staff, cash/expense controls, guest operations, delivery, and owner reporting without breaking the existing public ordering flow.

The release is successful when:

1. A customer/waiter order can move from table/order creation through kitchen preparation, payment and close without manual database edits.
2. Recipe-based stock changes are transactionally consistent with completed/cancelled/refunded orders.
3. Restaurant staff can operate with least-privilege roles; every sensitive action is auditable.
4. Managers can see tables, reservations, waitlist, kitchen delays, stock alerts, staff shifts, purchases and daily close from the admin application.
5. A crash/restart does not lose committed operational data.
6. Backup/restore, concurrent order tests and security regression tests pass before the build is called production-ready.
7. Existing public ordering, booking, menu, QR, promo, loyalty and KDS flows remain backward compatible unless this spec explicitly replaces behavior.

## 2. Scope boundaries

### In scope

- POS/table service workflow
- Floor plan/table state + waitlist
- Reservation-to-table assignment
- Advanced KDS with kitchen stations
- Inventory, units, recipes/BOM, stock movements and stock counts
- Waste/spoilage recording
- Supplier and purchasing workflow
- Staff accounts, roles, permissions, shifts and attendance
- Cash sessions, payments, expenses, refunds/voids and daily close
- CRM/loyalty enhancements
- Delivery assignment/status controls
- Owner dashboard and operational alerts
- Manager task/checklist system
- Immutable audit log
- Database migrations and automated QA

### Not in scope for this release

- Bank/payment-gateway integration requiring credentials from an external bank/provider
- Fiscal printer or government fiscal API integration without device/API documentation
- Payroll/tax calculation specific to Tajik regulation without the restaurant's accounting rules
- Multi-branch synchronization
- Native Android offline-first POS data replication

The data model and service boundaries must not prevent these later integrations.

## 3. Architecture decision

Use the existing Python + SQLite application as the production base, but modularize backend responsibilities. Do **not** rewrite the working public experience.

Target structure:

```text
bosfor/
  app.py / server.py                 # thin HTTP entrypoint
  bosfor/
    db.py                            # connections, migrations, transactions
    auth.py                          # sessions, password verification, RBAC
    audit.py                         # immutable audit events
    orders.py                        # order/POS domain logic
    tables.py                        # floor/table/waitlist/reservations
    kitchen.py                       # station routing and KDS state
    inventory.py                     # ingredients, recipes, stock ledger/counts
    purchasing.py                    # suppliers, POs, receiving
    staff.py                         # employees, shifts, attendance
    finance.py                       # payments, cash sessions, expenses, close
    crm.py                           # customers, loyalty, notes/tags
    delivery.py                      # zones, courier assignment, statuses
    reports.py                       # aggregates and dashboards
    tasks.py                         # checklists/tasks/logbook
    validation.py                    # shared input rules
  public/
    ... existing public app ...
    admin/
      modules/                       # dashboard, POS, KDS, stock, staff, etc.
  private/
    bosfor.sqlite3
    uploads/
    backups/
```

SQLite remains valid for one restaurant if WAL, short transactions, foreign keys, uniqueness constraints and indexes are enforced. Business mutations must execute inside transactions. Database migrations must be versioned so existing installations upgrade safely.

## 4. Identity, roles and permissions

Replace the single all-powerful admin model with named staff accounts while retaining an owner bootstrap account.

Roles:

- **Owner:** full access including users, finance, settings, backups and audit.
- **Manager:** operations, menu, inventory, purchasing, staff scheduling, reports; no owner credential reset.
- **Cashier:** POS, payment, cash session, receipt, permitted refund/void limits.
- **Waiter:** tables, POS orders for assigned/available tables, guest notes required for service; no finance settings.
- **Kitchen:** KDS only, stock-out marking and preparation status.
- **Courier:** assigned delivery orders/status only.

Permissions are server-enforced. Hiding a button in the UI is not authorization.

Sensitive actions requiring audit events: login/logout failures, user/role change, price change, discount, void/refund, stock adjustment, waste, purchase receiving, cash adjustment, settings change, backup/restore and data deletion.

## 5. POS and order lifecycle

### Order types

- delivery
- pickup
- dine-in
- waiter/POS-created dine-in

### Order state model

```text
open -> confirmed -> preparing -> ready -> served/out_for_delivery -> paid -> closed
                 \-> cancelled
```

Payment is a separate state/ledger; an order can be partially paid before close.

Required POS capabilities:

- create/open table order
- add/remove quantity before kitchen send
- send new items to kitchen while keeping the table open
- add service notes
- move order to another table
- merge two open table orders when safe
- split bill by items or amount
- record cash/card/QR/wallet payment methods
- controlled discount/void/refund
- print/share receipt view
- close only when payment requirements are satisfied, unless an authorized manager override is recorded

All totals are recalculated server-side from order-item snapshots and current approved modifiers at the moment an item is added/sent.

## 6. Tables, floor plan, reservations and waitlist

Extend `tables_map` with operational state and floor coordinates/zone metadata.

Table state:

- free
- reserved
- seated
- ordering
- preparing
- eating
- bill
- cleaning
- out_of_service

A reservation may be assigned to a table. Seating creates/links an open dine-in order. Waitlist entries include party size, contact, arrival time, quoted wait, priority note and status. The system suggests eligible free tables by capacity/zone but final assignment remains a staff action.

The admin floor view must show table state in real time and expose the next valid actions, not arbitrary state jumps.

## 7. Kitchen Display Pro

Add `kitchen_stations` and per-dish station routing.

Example stations: Grill, Hot Kitchen, Cold Kitchen, Bar.

Each kitchen ticket has:

- order/table/reference
- items routed to the station
- sent time
- target prep minutes
- elapsed timer
- priority
- notes/modifiers
- state: queued, preparing, ready, recalled/cancelled

A dine-in order can remain open while multiple kitchen tickets are sent over time. KDS completion must not automatically mark payment complete.

The KDS highlights overdue tickets based on configurable thresholds. Sold-out/86 can disable an item for new ordering while preserving historical items.

## 8. Inventory and recipe costing

Use a stock ledger rather than a mutable single quantity as the source of truth.

Entities:

- inventory_items (ingredient/product)
- units and conversions
- recipes
- recipe_components
- stock_movements
- stock_counts
- waste_events
- reorder_rules

Stock movement types:

- purchase_receive
- sale_consume
- sale_reversal
- waste
- manual_adjustment
- stock_count_adjustment
- transfer (reserved for future locations)

Recipe consumption occurs when the configured operational event happens (default: order item becomes served/out_for_delivery; manager setting may choose kitchen-send for selected items). Cancellation/reversal creates compensating ledger entries; history is never rewritten.

Each dish can compute theoretical food cost from recipe quantities and latest weighted-average ingredient cost. Show food-cost percentage and flag missing recipe/cost data.

Low-stock alerts use on-hand minus reserved quantity against reorder point.

## 9. Purchasing and suppliers

Entities:

- suppliers
- supplier_items
- purchase_orders
- purchase_order_lines
- goods_receipts

Workflow:

```text
draft PO -> sent/approved -> partially received -> received/closed -> cancelled
```

Receiving updates the stock ledger and cost basis transactionally. Over-receipt requires manager permission and audit. Purchase history exposes last cost and cost variance.

A reorder assistant proposes quantities using reorder point/target stock but never places an external order automatically in this release.

## 10. Staff, shifts and attendance

Entities:

- staff_users
- roles/permissions
- shift_templates (optional)
- shifts
- clock_events

Capabilities:

- create/disable employee account
- assign role
- schedule shift
- clock in/out
- manager correction with reason + audit
- current on-duty view
- hours summary by date range

No payroll or tax calculation in this release.

## 11. Payments, cash sessions, expenses and daily close

Payments are immutable ledger rows linked to orders.

Supported recorded methods: cash, card, QR, wallet, mixed.

Cash flow:

1. cashier opens a cash session with opening cash;
2. cash payments and cash refunds affect expected drawer balance;
3. authorized cash-in/cash-out adjustments require reason;
4. session closes with counted cash;
5. system records expected vs counted variance.

Expenses record category, amount, payment method, note, timestamp and staff actor.

Daily close report includes:

- gross sales
- discounts
- refunds/voids
- net sales
- payment-method totals
- order count
- average check
- expenses
- theoretical COGS where recipes/costs are complete
- estimated gross margin
- cash-session variances

Financial reporting must clearly mark estimates when recipe/cost coverage is incomplete.

## 12. CRM and loyalty

Keep phone as the primary customer lookup key after normalization. Extend customer data with:

- visit count
- lifetime spend
- last visit
- average check
- loyalty balance/history
- tags
- staff notes
- favorite/high-frequency dishes computed from orders

Notes/tags are staff-only and must not appear in public APIs. Loyalty earn/redeem operations are ledgered rather than overwriting history.

## 13. Delivery operations

Add delivery zones with configurable fee, minimum order and optional service hours. An order stores the zone and fee snapshot used at checkout.

Delivery state:

```text
confirmed -> preparing -> ready -> assigned -> out_for_delivery -> delivered
```

Courier assignment requires a courier-role staff account. Customer tracking exposes only safe order status/ETA; never staff-private data.

Route optimization/maps are not part of this release.

## 14. Tasks, checklists and manager logbook

Create reusable checklist templates and task instances for:

- opening
- closing
- cleaning
- maintenance
- food safety/internal checks

Task states: pending, in_progress, done, skipped. Skipping requires a reason. Overdue items appear in manager alerts.

Manager logbook provides date, category, note, actor and optional related order/table/staff reference.

## 15. Owner dashboard and alerts

The owner dashboard must answer “what needs attention now?” before showing decorative charts.

Top live indicators:

- open orders
- active tables
- waiting parties
- active/overdue kitchen tickets
- sales today
- average check
- refunds/voids today
- cash variance warnings
- low/out-of-stock ingredients
- dishes disabled/sold out
- open purchase orders
- staff currently clocked in
- overdue tasks

Historical reports allow date-range filters and CSV export.

## 16. Database and migration strategy

- Add a `schema_migrations` table.
- Every migration has a monotonically increasing integer version and executes transactionally.
- Existing dishes/orders/bookings/customers/promotions/tables/settings data is migrated in place.
- New foreign keys use conservative delete rules; historical financial/order records are not cascade-deleted.
- Add indexes for active order status, order timestamps, booking date/time, normalized phone, stock item/time, ticket status/time, payments/order, shifts/staff/time and audit timestamps.
- Enable and verify `PRAGMA foreign_keys=ON` for every connection.
- Keep WAL and a busy timeout.

## 17. API strategy

Keep existing public API compatibility where possible. Add versioned admin-domain endpoints under `/api/admin/v1/...` and enforce RBAC in a shared authorization layer.

Representative endpoint groups:

- `/api/admin/v1/pos/*`
- `/api/admin/v1/floor/*`
- `/api/admin/v1/kitchen/*`
- `/api/admin/v1/inventory/*`
- `/api/admin/v1/purchasing/*`
- `/api/admin/v1/staff/*`
- `/api/admin/v1/finance/*`
- `/api/admin/v1/reports/*`
- `/api/admin/v1/tasks/*`
- `/api/admin/v1/audit/*`

Every mutation validates content type, payload size, authentication, permission and CSRF/session requirements. Error responses use a stable JSON shape with machine-readable code and safe human message.

## 18. Error handling and invariants

Hard invariants:

- no client-controlled price/total
- no negative stock adjustment without an explicit adjustment/reversal event
- no payment mutation by rewriting old rows
- no closed order modification without a controlled reopen/manager workflow
- no staff action beyond server-checked permission
- no table double-seating through concurrent requests
- no duplicate purchase receiving through retried requests
- no duplicate public order through retried idempotent requests

Conflict-prone mutations use transactions and uniqueness/idempotency keys.

## 19. UI design principles

Do not overload the existing admin with one giant page. Add a desktop-first operational shell with responsive tablet support and modules:

- Overview
- POS / Floor
- Orders
- Kitchen
- Reservations / Waitlist
- Menu
- Inventory
- Purchasing
- Guests
- Staff
- Finance
- Tasks
- Reports
- Settings
- Audit (Owner only)

Primary operational screens must use large touch targets and minimize text entry. Destructive/financial actions require confirmation and, when appropriate, reason input.

Russian/Tajik localization remains mandatory for operational UI labels introduced by this release.

## 20. Testing and acceptance gates

### Unit/domain tests

- totals/discount rules
- permission checks
- order state transitions
- table-state transitions
- recipe consumption/reversal
- weighted-average cost updates
- cash-session arithmetic
- loyalty ledger arithmetic
- purchase receiving and idempotency

### Integration tests

- public order -> kitchen -> served -> payment -> close -> inventory consumption
- QR table order -> floor state -> kitchen
- booking -> table assignment -> seated -> open order
- waitlist -> seat -> reservation/order linkage
- purchase -> receive -> stock/cost update
- cancel/refund -> payment and inventory consistency
- waste -> stock ledger + audit
- shift clock in/out and manager correction
- cash open -> payments -> expense/refund -> close variance
- backup -> restore copy -> integrity check

### Concurrency tests

- at least 100 concurrent public orders without lost committed orders
- concurrent attempts to seat the same table: exactly one succeeds
- duplicate purchase receive idempotency
- concurrent stock-consuming order transitions preserve ledger consistency

### Security tests

- unauthenticated admin APIs -> 401
- insufficient role -> 403
- missing/invalid CSRF on authenticated mutations -> 403
- private/source/database paths not publicly served
- stored/reflected XSS probes render inertly
- upload MIME/size/path validation
- brute-force/rate-limit controls
- customer tracking cannot enumerate private customer/staff data

### Release gate

A build is not called “production-ready” until automated tests pass, database integrity is OK, backup/restore is verified, and a manual end-to-end smoke test is completed on desktop plus a real Android/iPhone-class mobile browser after deployment.

## 21. Implementation sequence

To minimize regression risk, implementation proceeds in dependency order:

1. database migration framework + modular DB/auth/audit foundation
2. staff accounts/RBAC
3. POS order/payment model + table/floor state
4. KDS station/ticket model
5. inventory/recipes/stock ledger
6. suppliers/purchasing
7. reservations/waitlist enhancements
8. staff shifts/attendance
9. finance/cash sessions/expenses/daily close
10. CRM/loyalty ledger enhancements
11. delivery zones/courier workflow
12. tasks/checklists/logbook
13. owner dashboard/reports
14. frontend/admin modularization polish
15. full regression/security/concurrency/backup-restore QA

Each step must preserve all previously passing tests before the next step starts.
