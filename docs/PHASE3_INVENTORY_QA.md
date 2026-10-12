# Phase 3 Inventory & Purchasing QA — 2026-10-04

## Fresh verification

- `python -m pytest -q tests/test_inventory_purchase_integration.py` → 2 passed.
- `python -m pytest -q` → 50 passed.
- `python -m py_compile server.py bosfor/*.py` → exit 0.
- `git diff --check` → clean.

## Release-gate invariants verified

- Duplicate purchase receiving with the same idempotency key does not double stock.
- Purchase receiving updates stock and weighted-average cost transactionally.
- Recipe consumption appends immutable stock movements.
- Cancellation creates compensating stock movements instead of rewriting history.
- Waste and stock count adjustments remain auditable in the ledger.
- Concurrent served transitions do not double-consume recipe stock.
- Derived on-hand equals the sum of stock movements for the integration fixtures.
- SQLite `PRAGMA integrity_check` returns `ok` in integration tests.
- SQLite `PRAGMA foreign_key_check` returns no violations in integration tests.

## Known scope boundary

Phase 3 does not calculate tax/payroll and does not attempt supplier accounting beyond purchase order/receipt/cost history. Those concerns are outside the approved Phase 3 spec.
