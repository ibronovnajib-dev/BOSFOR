# Bosfor Restaurant OS — Phase 2 POS, Floor & KDS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a complete dine-in/POS/table workflow and station-based KDS while preserving current delivery/pickup/public orders.

**Architecture:** Add order/payment/table/kitchen domain modules and versioned admin APIs. Existing public orders are adapted into the new internal order model through compatibility functions rather than rewritten endpoints.

**Tech Stack:** Python + SQLite + vanilla JS admin modules + pytest.

**Spec:** `docs/superpowers/specs/2026-10-04-bosfor-restaurant-os-design.md`

## Global Constraints

- Order totals and item snapshots are server-authoritative.
- Payments are append-only ledger rows.
- Closed orders cannot be silently mutated.
- Exactly one concurrent seat operation may claim a free table.
- KDS completion never implies payment completion.

## Review Focus

- Adding items after a first kitchen send must create only new kitchen tickets.
- Split/merge/move must preserve item totals and payment allocation.
- Concurrent seat/move attempts must fail with conflict rather than corrupt floor state.
- Refund/void permissions must be enforced server-side.
- Existing public order tracking must continue exposing only safe fields.

---

### Task 1: POS order model and state machine
**Files:** Create `bosfor/orders.py`, `tests/test_orders_domain.py`; modify `bosfor/migrations.py`, `server.py`.
**Interfaces:** `create_pos_order(con, actor, order_type, table_id=None) -> Order`; `add_item(con, order_id, dish_id, qty, modifiers, note) -> OrderItem`; `transition_order(con, order_id, target, actor, reason=None) -> Order`; `recalculate_order(con, order_id) -> MoneyTotals`.
- [ ] Write failing tests for state transitions, server pricing, item snapshots, closed-order lock and manager reopen requirement.
- [ ] Run tests and confirm FAIL.
- [ ] Add normalized order/order_item schema migration and compatibility mapping from existing orders.
- [ ] Implement domain interfaces and adapt public order insertion to them.
- [ ] Run order + legacy tests; expected PASS.
- [ ] Commit `feat: add transactional POS order domain`.

### Task 2: Payment ledger, split bill and controlled discount/void/refund
**Files:** Create `bosfor/finance_ledger.py`, `tests/test_payments.py`; modify `bosfor/migrations.py`, `bosfor/orders.py`.
**Interfaces:** `record_payment(con, order_id, actor, method, amount, idempotency_key) -> Payment`; `apply_discount(con, order_id, actor, kind, value, reason) -> OrderAdjustment`; `refund_payment(con, payment_id, actor, amount, reason) -> Payment`; `payment_balance(con, order_id) -> PaymentBalance`.
- [ ] Write failing tests for mixed/partial payment, duplicate payment idempotency, refund append-only behavior and close-with-unpaid rejection.
- [ ] Run and confirm FAIL.
- [ ] Add payment/adjustment migrations and implement interfaces.
- [ ] Run tests; expected PASS.
- [ ] Commit `feat: add immutable payment and adjustment ledger`.

### Task 3: Floor/table operational state with concurrency control
**Files:** Create `bosfor/tables.py`, `tests/test_floor.py`; modify `bosfor/migrations.py`.
**Interfaces:** `seat_table(con, table_id, actor, reservation_id=None) -> Seating`; `set_table_state(con, table_id, target, actor) -> TableState`; `move_order(con, order_id, to_table_id, actor) -> Order`; `merge_orders(con, source_id, target_id, actor) -> Order`.
- [ ] Write failing tests for valid state graph and two concurrent seat attempts where exactly one succeeds.
- [ ] Run and confirm FAIL.
- [ ] Add coordinates/zone/state/version columns plus seating linkage migration; implement optimistic/transactional conflict handling.
- [ ] Run tests; expected PASS.
- [ ] Commit `feat: add live floor and table state engine`.

### Task 4: Admin POS/floor APIs
**Files:** Create `bosfor/api_pos.py`, `bosfor/api_floor.py`, `tests/test_pos_api.py`; modify `server.py`.
**Interfaces:** `/api/admin/v1/pos/orders`, `/items`, `/send`, `/payments`, `/discounts`, `/refunds`, `/close`; `/api/admin/v1/floor/tables`, `/seat`, `/move`, `/merge`.
- [ ] Write failing API tests for permissions, CSRF, conflicts, stable errors and successful waiter/cashier flows.
- [ ] Run and confirm FAIL.
- [ ] Implement handlers using domain modules only.
- [ ] Run API + domain + legacy tests; expected PASS.
- [ ] Commit `feat: expose RBAC POS and floor APIs`.

### Task 5: Kitchen stations, tickets and 86/sold-out
**Files:** Create `bosfor/kitchen.py`, `tests/test_kitchen.py`; modify `bosfor/migrations.py`, `bosfor/orders.py`.
**Interfaces:** `route_unsent_items(con, order_id, actor) -> list[KitchenTicket]`; `set_ticket_state(con, ticket_id, target, actor) -> KitchenTicket`; `set_dish_availability(con, dish_id, available, actor, reason) -> None`.
- [ ] Write failing tests for station routing, second send only routing new items, overdue calculation, recall/cancel and 86 blocking new item additions without altering history.
- [ ] Run and confirm FAIL.
- [ ] Add station/routing/ticket migrations and implement domain.
- [ ] Run tests; expected PASS.
- [ ] Commit `feat: add station-based kitchen ticket workflow`.

### Task 6: Operational admin UI modules
**Files:** Create `public/admin/app.js`, `public/admin/api.js`, `public/admin/modules/pos.js`, `public/admin/modules/floor.js`, `public/admin/modules/kitchen.js`, `public/admin/modules/common.js`, `public/admin/admin.css`; modify `public/admin.html`.
**Interfaces:** Modules consume Phase 2 admin APIs and shared localization/auth state.
- [ ] Add browserless JS syntax/static tests in `tests/test_admin_assets.py` for module presence, route wiring and no duplicate IDs.
- [ ] Run tests and confirm FAIL.
- [ ] Extract only POS/floor/kitchen shell from monolithic admin while keeping legacy sections functioning.
- [ ] Run static + API + legacy tests; expected PASS.
- [ ] Commit `feat: add touch-first POS floor and KDS admin modules`.

### Task 7: Phase 2 end-to-end gate
**Files:** Create `tests/test_pos_kds_integration.py`, `docs/PHASE2_POS_KDS_QA.md`.
**Interfaces:** Full flow: seat -> open POS -> add/send -> kitchen ready -> serve -> mixed payment -> close.
- [ ] Write the integration test with exact ledger/table/ticket assertions.
- [ ] Run Phase 2 suite and fix only defects revealed by tests.
- [ ] Run 100 concurrent public orders + concurrent same-table seat race.
- [ ] Verify SQLite integrity/FKs and document results.
- [ ] Commit `test: complete phase 2 POS floor KDS release gate`.
