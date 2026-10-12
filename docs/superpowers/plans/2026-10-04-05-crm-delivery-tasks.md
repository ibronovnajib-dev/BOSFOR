# Bosfor Restaurant OS — Phase 5 CRM, Delivery & Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade guest/loyalty intelligence, delivery control, and manager task/checklist/logbook operations.

**Architecture:** CRM derives visit/spend/favorites from closed order history while private notes/tags remain staff-only. Loyalty, delivery status and task history are ledger/event based; customer tracking returns a safe projection only.

**Tech Stack:** Python + SQLite + pytest + vanilla JS.

**Spec:** `docs/superpowers/specs/2026-10-04-bosfor-restaurant-os-design.md`

## Global Constraints
- Phone is normalized primary customer lookup key.
- Loyalty adjustments are ledgered.
- Customer tracking exposes no private staff/customer notes.
- Courier APIs operate only on assigned deliveries.
- Skipped tasks require a reason.

## Review Focus
- Phone normalization must not merge clearly different valid customers.
- Loyalty retry must not double earn/redeem.
- Courier cannot access another courier's assignment details.
- Delivery fee/minimum/service-hours snapshot must remain stable on existing order.
- Overdue/skipped task semantics must survive restart/time-zone handling.

---

### Task 1: CRM profiles, tags, notes and computed insights
**Files:** Create `bosfor/crm.py`, `tests/test_crm.py`; modify `bosfor/migrations.py`.
**Interfaces:** `get_or_create_customer(...)`; `customer_profile(...)`; `add_customer_tag(...)`; `add_customer_note(...)`; `recompute_customer_metrics(...)`.
- [ ] Write failing tests for normalized lookup, visit/lifetime/average/last visit, favorite dishes and private field exclusion.
- [ ] Run FAIL.
- [ ] Add CRM tables/indexes and implement computations.
- [ ] Run PASS.
- [ ] Commit `feat: add guest CRM profiles and order-derived insights`.

### Task 2: Loyalty ledger
**Files:** Modify `bosfor/crm.py`; create `tests/test_loyalty_ledger.py`.
**Interfaces:** `earn_points(...)`; `redeem_points(...)`; `loyalty_balance(...)`; `reverse_loyalty_event(...)`.
- [ ] Write failing tests for earn/redeem/retry/reversal/no-negative-balance rules.
- [ ] Run FAIL.
- [ ] Add loyalty ledger migration and implement idempotent events.
- [ ] Run PASS.
- [ ] Commit `feat: replace loyalty overwrite with immutable ledger`.

### Task 3: Delivery zones and courier workflow
**Files:** Create `bosfor/delivery.py`, `tests/test_delivery.py`; modify `bosfor/migrations.py`, `bosfor/orders.py`.
**Interfaces:** `quote_delivery(con, zone_id, subtotal, when) -> DeliveryQuote`; `assign_courier(...)`; `transition_delivery(...)`; `safe_tracking_view(...)`.
- [ ] Write failing tests for zone fee/minimum/hours, snapshot persistence, courier assignment authorization and safe tracking.
- [ ] Run FAIL.
- [ ] Add zone/assignment schema and implement.
- [ ] Run PASS.
- [ ] Commit `feat: add delivery zone and courier operations`.

### Task 4: Checklists, tasks and manager logbook
**Files:** Create `bosfor/tasks.py`, `tests/test_tasks.py`; modify `bosfor/migrations.py`.
**Interfaces:** `create_template(...)`; `instantiate_checklist(...)`; `transition_task(...)`; `overdue_tasks(...)`; `add_logbook_entry(...)`.
- [ ] Write failing tests for pending/in-progress/done/skipped, skip reason, overdue calculation and related references.
- [ ] Run FAIL.
- [ ] Add task/template/logbook schema and implement.
- [ ] Run PASS.
- [ ] Commit `feat: add operational checklists tasks and logbook`.

### Task 5: CRM/delivery/tasks admin modules
**Files:** Create `public/admin/modules/guests.js`, `delivery.js`, `tasks.js`; modify `public/admin.html`, `public/admin/admin.css`; create `tests/test_phase5_admin_assets.py`.
**Interfaces:** Consume `/api/admin/v1/crm/*`, `/delivery/*`, `/tasks/*`.
- [ ] Write failing API/static contract tests.
- [ ] Run FAIL.
- [ ] Implement role-aware modules and customer-safe/public tracking separation.
- [ ] Run PASS.
- [ ] Commit `feat: add CRM delivery and task management UI`.

### Task 6: Phase 5 release gate
**Files:** Create `tests/test_phase5_integration.py`, `docs/PHASE5_CRM_DELIVERY_TASKS_QA.md`.
**Interfaces:** closed order->CRM/loyalty; delivery quote->assign->deliver->safe track; checklist->overdue/complete/logbook.
- [ ] Write integration tests with ledger/privacy assertions.
- [ ] Run Phase 1-5 suites.
- [ ] Probe order-tracking enumeration/privacy and courier cross-access.
- [ ] Verify DB integrity/FKs and document.
- [ ] Commit `test: complete phase 5 guest delivery tasks release gate`.
