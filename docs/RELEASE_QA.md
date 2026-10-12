# BOSFOR Restaurant OS — Release QA

Date: 2026-10-04
Branch: `feature/restaurant-os`

## Automated release gate

### Full Python suite
Command:
```bash
python -m pytest -q
```
Result: **125 passed in 26.14s**.

### Python compilation
Command:
```bash
python -m py_compile server.py bosfor/*.py
```
Result: **PASS**.

### Admin/service-worker JavaScript syntax
Command:
```bash
for f in public/admin/legacy.js public/admin/app.js public/admin/i18n.js public/admin/router.js public/admin/modules/*.js public/sw.js; do node --check "$f"; done
```
Result: **20 JavaScript files PASS**.

### Focused release/security/backup/diagnostics suite
Command:
```bash
python -m pytest -q tests/test_release_static.py tests/security tests/test_backup_restore.py tests/test_diagnostics.py
```
Result: **19 passed in 10.38s**.

### Git whitespace/error scan
Command:
```bash
git diff --check
```
Result: **PASS**.

### Concurrency/invariant stress gate
The critical concurrency group was executed five consecutive times. Each loop included:
- 100 simultaneous public orders with zero lost committed orders;
- same-table seat race with exactly one winner;
- concurrent payment overpay protection;
- concurrent KDS send idempotency;
- duplicate/concurrent goods receiving with one stock effect;
- concurrent recipe stock consumption;
- concurrent loyalty idempotency;
- concurrent task completion terminal-state protection.

Result: **5/5 loops PASS; 8/8 tests per loop**.

### Backup/restore gate
Verified by automated round-trip tests:
- online SQLite backup;
- DB SHA-256 manifest;
- uploaded-asset checksums;
- tamper detection;
- restore into a new location;
- order/payment/stock/audit row preservation;
- `PRAGMA integrity_check = ok`;
- `PRAGMA foreign_key_check = 0`;
- admin password, `.env`, DB runtime secrets and prior backup contents excluded.

## Security gate
Verified:
- named staff authentication with DB-backed sessions;
- Owner / Manager / Cashier / Waiter / Kitchen / Courier server-side authorization;
- immediate role changes and disabled-account session invalidation;
- owner-only user management, audit and detailed diagnostics;
- CSRF on authenticated mutations;
- `application/json` enforcement for API mutations;
- image MIME/magic/size validation;
- private/source paths are not served;
- login brute-force rate limiting;
- public tracking safe-field constraints;
- immutable audit log;
- release archive allowlist excludes runtime secrets.

## Operational modules included
- POS/table service and floor state;
- KDS/station routing and 86/sold-out;
- inventory ledger, recipes, food-cost coverage, waste/counts;
- suppliers, purchase orders and receiving;
- reservations and waitlist;
- staff shifts/attendance;
- cash sessions, expenses and daily close;
- CRM, tags/notes and immutable loyalty ledger;
- delivery zones/courier tracking;
- tasks/checklists and manager logbook;
- owner dashboard/reports;
- staff account/RBAC management;
- immutable audit viewer;
- diagnostics;
- verified backup/restore;
- clean release builder.

## Final whole-branch self-review

A fresh subagent reviewer was not available in this harness, so the final branch review was performed as a separate author self-review (weaker than an independent reviewer). Two Important UI/authorization mismatches were found and fixed with RED→GREEN tests:

- Waiter/Cashier/Courier navigation exposed tabs whose server APIs were not available to those roles. Fixed by aligning the navigation matrix with server capabilities and using role-priority landing tabs.
- Cashier Finance displayed manager-only daily-report/expense controls. Fixed by rendering a cashier-specific cash-session view while keeping manager/owner finance controls separate.

Post-fix full suite: **125/125 PASS**.

## Clean-artifact local smoke

The generated release archive was extracted into a new empty directory and started with a fresh runtime DB. Verified:
- public health;
- public Bosfor page;
- owner login;
- owner diagnostics;
- admin creates initial menu item on a clean DB;
- public customer order succeeds against that server-side menu.

The clean release intentionally does not ship unverified restaurant menu/prices; the owner must import/enter the confirmed real menu before launch.

## Manual deployed smoke gate — NOT YET CONFIRMED

The release must **not** be labelled 100% production-ready until these checks are performed against the real HTTPS deployment and real devices:

- Owner login, then create real waiter/cashier/kitchen/courier accounts.
- QR dine-in -> table seat -> waiter item -> KDS -> serve -> mixed payment -> close -> stock consumption.
- Booking/waitlist -> seat; purchase receive -> stock; cash open/close; checklist; delivery tracking.
- Real desktop + Android + iPhone-class browser responsive checks.
- Logo/menu-photo upload and printed/scanned physical table QR.
- HTTPS Secure-cookie behavior, mixed-content check and browser-console check.
- A real backup, restore to a separate location, and integrity validation.

External data/configuration still required where applicable: confirmed real menu/prices/photos/allergens, physical table map/numbers, production domain/HTTPS, delivery rules, Telegram/SMS credentials and payment-provider credentials.

The SHA-256 for the generated release ZIP is produced after this tracked QA document is committed and is distributed as a sidecar `.sha256` file, avoiding a self-referential archive hash.
