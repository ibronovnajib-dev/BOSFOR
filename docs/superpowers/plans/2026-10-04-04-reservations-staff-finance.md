# Bosfor Restaurant OS — Phase 4 Reservations, Staff & Finance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add waitlist/reservation-to-table operations, staff shifts/attendance, cash sessions, expenses and trustworthy daily close reporting.

**Architecture:** Reservations/floor remain operational domain state; attendance and finance are append-only event/ledger models with manager corrections recorded as new events plus audit.

**Tech Stack:** Python + SQLite + pytest + vanilla JS.

**Spec:** `docs/superpowers/specs/2026-10-04-bosfor-restaurant-os-design.md`

## Global Constraints
- No payroll/tax calculation.
- Cash/payment historical rows are immutable.
- Manager corrections require reason and audit.
- Reservation seating must reuse floor concurrency safeguards.
- Financial estimates clearly expose incomplete COGS coverage.

## Review Focus
- Reservation and walk-in cannot double-seat one table.
- Overnight shifts/date boundaries must calculate hours predictably.
- Cash refund and cash-out must affect expected drawer exactly once.
- A close variance must remain historically reproducible after restart.
- No-show/cancelled reservations must not inflate seated/visit metrics.

---

### Task 1: Reservations and waitlist domain
**Files:** Create `bosfor/reservations.py`, `tests/test_reservations_waitlist.py`; modify `bosfor/migrations.py`, `bosfor/tables.py`.
**Interfaces:** `create_waitlist_entry(...)`; `quote_wait(...)`; `assign_reservation_table(...)`; `seat_reservation(...)`; `seat_waitlist_entry(...)`.
- [ ] Write failing tests for capacity suggestions, assignment, no-show/cancel, waitlist->seat and concurrent table claim.
- [ ] Run FAIL.
- [ ] Add waitlist/reservation linkage migration and implement using floor transactions.
- [ ] Run PASS.
- [ ] Commit `feat: add reservation and waitlist seating workflow`.

### Task 2: Staff shifts and clock events
**Files:** Create `bosfor/staff.py`, `tests/test_staff_shifts.py`; modify `bosfor/migrations.py`.
**Interfaces:** `schedule_shift(...)`; `clock_in(...)`; `clock_out(...)`; `correct_clock_event(..., reason)`; `hours_summary(...)`.
- [ ] Write failing tests for schedule, duplicate clock-in prevention, overnight hours and manager correction audit.
- [ ] Run FAIL.
- [ ] Add shift/clock schema and implement.
- [ ] Run PASS.
- [ ] Commit `feat: add staff scheduling and attendance events`.

### Task 3: Cash sessions and drawer arithmetic
**Files:** Create `bosfor/finance.py`, `tests/test_cash_sessions.py`; modify `bosfor/migrations.py`, `bosfor/finance_ledger.py`.
**Interfaces:** `open_cash_session(...)`; `record_cash_adjustment(...)`; `close_cash_session(..., counted_cash) -> CashClose`; `expected_cash(...) -> Decimal`.
- [ ] Write failing tests for opening cash, payments, refunds, cash-in/out, duplicate close rejection and variance.
- [ ] Run FAIL.
- [ ] Implement schema/domain and cashier permissions.
- [ ] Run PASS.
- [ ] Commit `feat: add cash drawer session controls`.

### Task 4: Expenses and daily close report
**Files:** Modify `bosfor/finance.py`; create `tests/test_daily_close.py`.
**Interfaces:** `record_expense(...)`; `daily_close(con, business_date) -> DailyCloseReport`.
- [ ] Write failing tests for gross/discount/refund/net/payment totals, average check, expenses, COGS estimate labeling and cash variance warnings.
- [ ] Run FAIL.
- [ ] Implement expense ledger and report aggregation.
- [ ] Run PASS.
- [ ] Commit `feat: add expenses and daily close reporting`.

### Task 5: Reservations/staff/finance admin modules
**Files:** Create `public/admin/modules/reservations.js`, `staff.js`, `finance.js`; modify `public/admin.html`, `public/admin/admin.css`; create `tests/test_phase4_admin_assets.py`.
**Interfaces:** Consume `/api/admin/v1/reservations/*`, `/staff/*`, `/finance/*`.
- [ ] Write failing API/static contract tests.
- [ ] Run FAIL.
- [ ] Implement modules with role-specific controls and reason dialogs.
- [ ] Run PASS.
- [ ] Commit `feat: add reservations staff and finance operations UI`.

### Task 6: Phase 4 release gate
**Files:** Create `tests/test_phase4_integration.py`, `docs/PHASE4_OPERATIONS_QA.md`.
**Interfaces:** booking->table->POS plus shift->cash open->sales/refund->expense->cash close->daily close.
- [ ] Write full integration assertions.
- [ ] Run Phase 1-4 suites.
- [ ] Restart and recompute daily close/cash variance to prove reproducibility.
- [ ] Verify DB integrity/FKs and document.
- [ ] Commit `test: complete phase 4 operations release gate`.
