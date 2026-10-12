# Bosfor Restaurant OS — Phase 3 Inventory, Recipes & Purchasing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add recipe-based stock, cost visibility, waste/counting, suppliers and purchase receiving with ledger consistency.

**Architecture:** Inventory is ledger-first: on-hand is derived from stock movements, not overwritten quantities. Recipe consumption and purchasing append compensating movements inside the same transaction as the operational event.

**Tech Stack:** Python + SQLite + pytest + vanilla JS admin modules.

**Spec:** `docs/superpowers/specs/2026-10-04-bosfor-restaurant-os-design.md`

## Global Constraints
- Historical stock movements are immutable.
- Negative adjustments require explicit adjustment/reversal reasons and permission.
- Purchase receiving is idempotent.
- Costing uses weighted-average ingredient cost and clearly reports missing coverage.
- Order cancellation/reversal must create compensating stock movements.

## Review Focus
- Unit conversion precision and rounding must not drift on repeated operations.
- A duplicate receive request must not double stock or supplier cost.
- Partial recipe coverage must not produce a falsely precise food-cost percentage.
- Concurrent sale consumption must preserve ledger/on-hand consistency.
- Stock count adjustments must be auditable and reproducible.

---

### Task 1: Inventory item/unit/conversion foundation
**Files:** Create `bosfor/inventory.py`, `tests/test_inventory_units.py`; modify `bosfor/migrations.py`.
**Interfaces:** `create_inventory_item(...)`; `convert_quantity(con, quantity, from_unit, to_unit) -> Decimal`; `on_hand(con, item_id) -> Decimal`; `append_movement(...) -> StockMovement`.
- [ ] Write failing tests for base units, conversions, append-only movement and on-hand derivation.
- [ ] Run FAIL.
- [ ] Add item/unit/conversion/movement migrations and implement interfaces using Decimal-safe serialization.
- [ ] Run PASS.
- [ ] Commit `feat: add stock ledger and unit conversion foundation`.

### Task 2: Recipes/BOM and theoretical costing
**Files:** Create `bosfor/recipes.py`, `tests/test_recipes.py`; modify `bosfor/migrations.py`.
**Interfaces:** `set_recipe(con, dish_id, components, actor) -> Recipe`; `recipe_cost(con, dish_id) -> RecipeCost`; `recipe_coverage(con, dish_id) -> Coverage`.
- [ ] Write failing tests for component quantities, weighted cost, missing cost coverage and percent calculation.
- [ ] Run FAIL.
- [ ] Add recipe schema and implement cost/coverage.
- [ ] Run PASS.
- [ ] Commit `feat: add recipes and theoretical food costing`.

### Task 3: Sale consumption/reversal integration
**Files:** Modify `bosfor/inventory.py`, `bosfor/orders.py`; create `tests/test_sale_inventory_integration.py`.
**Interfaces:** `consume_order_items(con, order_id, trigger, actor) -> list[StockMovement]`; `reverse_order_consumption(con, order_id, actor, reason) -> list[StockMovement]`.
- [ ] Write failing tests for configured served/out-for-delivery trigger, idempotency, cancellation reversal and concurrent consumption.
- [ ] Run FAIL.
- [ ] Implement consumption in the same transaction as order transition.
- [ ] Run PASS including concurrency case.
- [ ] Commit `feat: connect order lifecycle to recipe stock consumption`.

### Task 4: Waste, stock counts, reorder alerts
**Files:** Modify `bosfor/inventory.py`; create `tests/test_stock_controls.py`.
**Interfaces:** `record_waste(...)`; `complete_stock_count(...)`; `low_stock_items(con) -> list[LowStockAlert]`.
- [ ] Write failing tests for waste reason/audit, count variance movement, reorder threshold using on-hand minus reserved.
- [ ] Run FAIL.
- [ ] Implement and expose admin APIs `/api/admin/v1/inventory/*`.
- [ ] Run PASS.
- [ ] Commit `feat: add waste counts and low-stock controls`.

### Task 5: Suppliers, POs and idempotent receiving
**Files:** Create `bosfor/purchasing.py`, `tests/test_purchasing.py`; modify `bosfor/migrations.py`.
**Interfaces:** `create_purchase_order(...)`; `approve_po(...)`; `receive_po(con, po_id, lines, actor, idempotency_key) -> GoodsReceipt`; `suggest_reorder(con) -> list[ReorderSuggestion]`.
- [ ] Write failing tests for draft->approved->partial->received, over-receive permission, weighted cost update and duplicate idempotency.
- [ ] Run FAIL.
- [ ] Add supplier/PO/receipt schema and implement transactional receiving.
- [ ] Run PASS.
- [ ] Commit `feat: add supplier purchase order and receiving workflow`.

### Task 6: Inventory/purchasing admin modules
**Files:** Create `public/admin/modules/inventory.js`, `public/admin/modules/purchasing.js`; modify `public/admin.html`, `public/admin/admin.css`; create `tests/test_inventory_admin_assets.py`.
**Interfaces:** Consume `/api/admin/v1/inventory/*` and `/api/admin/v1/purchasing/*`.
- [ ] Write failing static/API contract tests for stock list, recipe editor, count/waste, low-stock, supplier, PO and receiving flows.
- [ ] Run FAIL.
- [ ] Implement responsive modules with confirmation/reason on destructive adjustments.
- [ ] Run PASS.
- [ ] Commit `feat: add inventory recipe and purchasing back office`.

### Task 7: Phase 3 release gate
**Files:** Create `tests/test_inventory_purchase_integration.py`, `docs/PHASE3_INVENTORY_QA.md`.
**Interfaces:** purchase receive -> stock/cost -> POS sale -> recipe consume -> cancel reversal -> count/waste.
- [ ] Write and run end-to-end ledger assertions.
- [ ] Run concurrent stock-consuming transitions and duplicate receive retries.
- [ ] Verify `sum(stock_movements)` equals derived on-hand for every item fixture.
- [ ] Run integrity/FK checks and document results.
- [ ] Commit `test: complete phase 3 inventory purchasing release gate`.
