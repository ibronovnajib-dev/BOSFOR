# Phase 4 Reservations, Staff & Finance QA — 2026-10-04

## Fresh verification

- `python -m pytest -q` → 67 passed.
- `python -m py_compile server.py bosfor/*.py` → exit 0.
- `node --check public/admin/app.js` and every `public/admin/modules/*.js` → exit 0.
- `git diff --check` → clean.

## Release-gate flows verified

- Reservation assignment -> reserved table -> seating -> POS order.
- Reservation cancellation/no-show releases reserved tables.
- Walk-in cannot take a table reserved for another guest.
- Concurrent reservation/walk-in attempts cannot create two active orders on one table.
- Staff schedule, clock-in/out, overnight duration, append-only correction.
- Non-manager staff can clock only their own staff identity.
- Cash session opening, cash payments/refunds, cash-in/out, close variance.
- Expense ledger is append-only and manager controlled.
- Daily close reports gross, discounts, net sales, refunds, payment methods, expenses, COGS coverage and cash variance.
- Daily close and cash variance reproduce identically after SQLite restart.
- SQLite integrity check = `ok`; foreign-key check returns no violations in integration gate.

## Review fix-pass

- Blocked walk-in/manual seating from consuming a table in `reserved` state without a reservation id.
- Removed role-prefix shortcut that could let a staff user clock another identity.
