# Phase 2 POS / Floor / KDS QA

Date: 2026-10-04

## Scope verified

- Transactional POS order state machine with server-authoritative price snapshots.
- Append-only payment/refund ledger, discount permissions and unpaid-close guard.
- Live floor/table state with concurrent seat conflict protection.
- RBAC + CSRF versioned admin APIs for POS/floor/KDS.
- Station-based KDS with incremental sends, overdue timers, recall/cancel and 86/sold-out.
- Touch-first modular admin UI for POS, floor and KDS while legacy sections remain available.
- Public ordering remains backward compatible and respects kitchen 86 state.
- Public order tracking exposes only safe fields.

## Fresh verification

Commands run from the Phase 2 worktree:

```bash
python -m py_compile server.py bosfor/*.py
node --check public/admin/app.js
node --check public/admin/api.js
node --check public/admin/modules/common.js
node --check public/admin/modules/pos.js
node --check public/admin/modules/floor.js
node --check public/admin/modules/kitchen.js
python -m pytest -q
```

Result: **31 passed, 0 failed**.

The suite includes:

- full seat → POS → send → KDS → serve → mixed payment → close flow;
- table release into `cleaning` state and seating end timestamp after close;
- two simultaneous seat attempts where exactly one succeeds;
- two simultaneous kitchen sends route each quantity exactly once;
- concurrent payments cannot overpay the order;
- repeated schema guards preserve active SQLite transactions;
- kitchen role is denied access to POS/payment views;
- direct POS dine-in creation atomically claims the table;
- 100 simultaneous public orders with 100/100 persisted;
- `PRAGMA integrity_check = ok`;
- `PRAGMA foreign_key_check = []`;
- safe public tracking response;
- 86/sold-out enforcement for both staff POS and public customer ordering;
- no duplicate static IDs in admin HTML and JS syntax checks.

## Release note

Phase 2 is considered code-verified for the automated scope above. Real-device visual QA and production HTTPS/deployment validation remain part of the final release phase rather than this phase gate.
