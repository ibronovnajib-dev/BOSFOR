# Bosfor Restaurant OS Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement these plans in order. Do not start a later phase until the previous phase's release gate passes.

**Goal:** Turn the current Bosfor ordering/admin application into a modular single-restaurant Restaurant OS while preserving all working public ordering, booking, QR, promo, loyalty, upload, and KDS behavior.

**Architecture:** Keep Python + SQLite + existing public HTML as the base. Incrementally extract domain modules behind a thin HTTP entrypoint, add versioned migrations and RBAC, then layer POS/floor/KDS, inventory/purchasing, reservations/staff/finance, CRM/delivery/tasks, and finally reporting/admin modularization/release QA.

**Tech Stack:** Python 3.11+, stdlib HTTP server during this release, SQLite 3 with WAL/foreign keys/busy timeout, vanilla HTML/CSS/JS, pytest for automated tests, qrcode for printable table QR.

**Spec:** `docs/superpowers/specs/2026-10-04-bosfor-restaurant-os-design.md`

## Global Constraints

- Preserve backward compatibility for `/api/order`, `/api/booking`, `/api/dishes`, `/api/settings`, `/api/tables`, `/api/order-track` unless the spec explicitly replaces behavior.
- Public/client totals are never trusted; price/discount/fee/tax totals are recalculated server-side.
- Every mutation that can race executes inside a short SQLite transaction.
- Every SQLite connection enables `PRAGMA foreign_keys=ON`, WAL, and a non-zero busy timeout.
- New admin-domain APIs live under `/api/admin/v1/...` and use server-enforced RBAC plus session/CSRF checks.
- Historical order, payment, stock, audit, and financial ledger rows are append-only; corrections use compensating records.
- Russian/Tajik localization is mandatory for new operational UI labels.
- No bank gateway, fiscal device, payroll/tax, multi-branch sync, or native offline POS replication in this release.

## Review Focus

- Retry/idempotency: repeated POSTs must not duplicate public orders, goods receipts, stock consumption, or financial rows.
- Concurrency: two staff actions cannot double-seat one table or corrupt stock/order state.
- Authorization: direct API calls by an insufficient role must fail even if UI controls are hidden.
- Partial/incomplete costing: reports must label theoretical COGS/gross margin as estimated when recipe/cost coverage is incomplete.
- Recovery: a restart or restore must preserve committed data and pass SQLite integrity/foreign-key checks.

## Execution Order

1. `2026-10-04-01-foundation-rbac-audit.md`
2. `2026-10-04-02-pos-floor-kds.md`
3. `2026-10-04-03-inventory-purchasing.md`
4. `2026-10-04-04-reservations-staff-finance.md`
5. `2026-10-04-05-crm-delivery-tasks.md`
6. `2026-10-04-06-dashboard-admin-release-qa.md`

Each phase is independently reviewable and must leave the application runnable with all earlier tests green.
