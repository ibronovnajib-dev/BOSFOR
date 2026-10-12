# Bosfor Restaurant OS — Phase 6 Dashboard, Admin Modularization & Release QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the owner dashboard/reports, modularize the operational admin shell, verify backup/restore/security/concurrency, and produce the production candidate.

**Architecture:** Reporting queries aggregate from immutable operational ledgers. The admin becomes a module shell with shared API/auth/i18n utilities; server remains thin and domain modules own business rules. Release packaging excludes secrets, DB fixtures, `.git`, and test artifacts.

**Tech Stack:** Python + SQLite + pytest + vanilla JS/CSS + qrcode.

**Spec:** `docs/superpowers/specs/2026-10-04-bosfor-restaurant-os-design.md`

## Global Constraints
- Dashboard prioritizes actionable alerts over decorative charts.
- Reports distinguish actual values from estimates.
- Audit is Owner-only.
- Release is not called production-ready until automated, integrity, backup/restore and manual deployed smoke gates pass.
- Public mobile ordering remains backward compatible.

## Review Focus
- Date/time aggregation must use Asia/Dushanbe business dates consistently.
- CSV export must neutralize spreadsheet formula injection for user-controlled text.
- Backup/restore must include DB and required uploaded assets without secrets leakage.
- Rate limiting/security hardening must not break legitimate kitchen/POS polling.
- Admin module failure must show a recoverable error instead of leaving an unsafe half-submitted action.

---

### Task 1: Reports and owner live dashboard service
**Files:** Create `bosfor/reports.py`, `tests/test_reports.py`; modify `server.py`.
**Interfaces:** `live_dashboard(con, now) -> Dashboard`; `historical_report(con, date_from, date_to) -> Report`; `export_csv(report_type, rows) -> str`.
- [ ] Write failing tests for all live indicators from spec, date ranges, estimate labels and CSV formula neutralization.
- [ ] Run FAIL.
- [ ] Implement aggregates/index-aware queries and `/api/admin/v1/reports/*`.
- [ ] Run PASS.
- [ ] Commit `feat: add actionable owner dashboard and reports`.

### Task 2: Complete admin shell modularization and localization
**Files:** Create/modify `public/admin/app.js`, `api.js`, `i18n.js`, `router.js`, `admin.css`, module files; reduce `public/admin.html` to semantic shell; create `tests/test_admin_shell.py`.
**Interfaces:** Shared `api.get/post`, auth principal/permissions, route registry, TJ/RU dictionary.
- [ ] Write failing static tests for no inline business logic in `admin.html`, module registry, permission-based navigation and TJ/RU key completeness.
- [ ] Run FAIL.
- [ ] Extract remaining legacy sections (orders/menu/settings/promos/QR/audit/reports) into modules without changing API behavior.
- [ ] Run static + all integration tests.
- [ ] Commit `refactor: modularize Bosfor operational admin shell`.

### Task 3: Backup and restore verification
**Files:** Create `bosfor/backup.py`, `tests/test_backup_restore.py`; modify `backup.sh`, `README_PRODUCTION.md`.
**Interfaces:** `create_backup(db_path, uploads_dir, destination) -> BackupManifest`; `verify_backup(path) -> Verification`; `restore_to_new_location(path, destination) -> RestoreResult`.
- [ ] Write failing test that seeds orders/payments/stock/audit/uploads, creates backup, restores to a new temp location and compares counts/checksums.
- [ ] Run FAIL.
- [ ] Implement SQLite online backup + asset manifest/checksums; never package admin password/secrets.
- [ ] Run restore test plus `integrity_check`/`foreign_key_check`.
- [ ] Commit `feat: add verified database and asset backup restore`.

### Task 4: Full security regression suite
**Files:** Create `tests/security/test_authz.py`, `test_csrf_upload_xss.py`, `test_public_privacy.py`, `test_rate_limits.py`.
**Interfaces:** Exercises all `/api/admin/v1/*`, public tracking, uploads and static serving.
- [ ] Add tests for unauthenticated 401, every role's forbidden endpoints 403, CSRF, upload MIME/size/path, stored/reflected XSS inertness, private paths 404, brute force/rate limits and customer enumeration resistance.
- [ ] Run suite and fix product defects only.
- [ ] Re-run entire test suite.
- [ ] Commit `test: harden full Restaurant OS security boundary`.

### Task 5: Full concurrency/invariant suite
**Files:** Create `tests/concurrency/test_orders_tables_stock_receiving.py`.
**Interfaces:** Public order, floor seat, stock consumption, goods receipt idempotency.
- [ ] Add 100 concurrent public order test with zero lost committed orders.
- [ ] Add concurrent same-table seat race; exactly one success.
- [ ] Add duplicate goods receipt retry/concurrent receive test; one stock effect.
- [ ] Add concurrent stock-consuming order transitions and assert ledger consistency.
- [ ] Run repeatedly (minimum 5 loops) with zero invariant failures.
- [ ] Commit `test: verify Restaurant OS concurrency invariants`.

### Task 6: Production diagnostics and release packaging
**Files:** Create `bosfor/diagnostics.py`, `tests/test_diagnostics.py`, `docs/RELEASE_QA.md`; modify `server.py`, `.gitignore`, `README_PRODUCTION.md`.
**Interfaces:** `/api/health` safe summary; owner-only `/api/admin/v1/diagnostics` detailed checks.
- [ ] Write failing tests for DB integrity/FK/schema version/storage/backup-age diagnostics with no secret exposure.
- [ ] Implement diagnostics and release pack script excluding DB, secrets, `.git`, test caches, backup contents.
- [ ] Run all automated tests, JS syntax checks and static asset/reference checks.
- [ ] Generate clean production ZIP and SHA-256, record exact commands/results in `docs/RELEASE_QA.md`.
- [ ] Commit `build: create verified Restaurant OS production candidate`.

### Task 7: Manual deployed smoke gate (required before "100% production-ready")
**Files:** Modify `docs/RELEASE_QA.md` only.
**Interfaces:** Deployed HTTPS environment with real desktop + Android/iPhone-class browser.
- [ ] Owner login -> dashboard -> create waiter/cashier/kitchen/courier accounts.
- [ ] QR dine-in -> seat/table -> waiter add item -> KDS -> serve -> mixed payment -> close -> stock consumed.
- [ ] Booking/waitlist -> seat; purchase receive -> stock update; cash open/close; task checklist; delivery tracking.
- [ ] Test responsive public/admin on desktop and real mobile, upload logo/menu photo, print/scan table QR.
- [ ] Confirm HTTPS cookie behavior, no mixed content, no console-breaking errors, backup/restore copy valid.
- [ ] Record any external-data blockers (real menu, payment/SMS credentials, domain/HTTPS) explicitly; do not label them code-complete if unavailable.
