# Bosfor Restaurant OS — Phase 1 Foundation, RBAC & Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the modular database/auth/audit foundation and named staff RBAC without breaking the existing public/admin flows.

**Architecture:** Introduce a `bosfor/` package behind the current `server.py`; keep `server.py` as the HTTP compatibility entrypoint. Add transactional numbered migrations, centralized connection setup, stable JSON errors, staff accounts/roles/permissions, and append-only audit events.

**Tech Stack:** Python 3.11+, SQLite/WAL, stdlib HTTP server, pytest.

**Spec:** `docs/superpowers/specs/2026-10-04-bosfor-restaurant-os-design.md`

## Global Constraints

- Existing public endpoints stay compatible.
- SQLite foreign keys, WAL and busy timeout are enabled on every connection.
- Owner bootstrap works from `BOSFOR_ADMIN_PASSWORD`/existing password file only for migration/bootstrap; operational auth becomes named staff sessions.
- UI hiding is never authorization.
- Sensitive actions listed in the spec emit immutable audit records.

## Review Focus

- Existing databases with legacy tables/data must migrate in place without loss.
- Re-running migrations must be idempotent and not duplicate schema/data.
- Disabled staff accounts or role changes invalidate effective permissions immediately.
- Expired/deleted sessions cannot mutate admin APIs.
- Audit writes must not be skipped on a successful sensitive mutation.

---

### Task 1: Test harness and compatibility baseline

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_legacy_regression.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: current `server.py` public/admin endpoints.
- Produces: pytest fixtures `app_env(tmp_path)`, `http_client(server_url)` and baseline assertions later phases must preserve.

- [ ] **Step 1: Write failing/characterization tests** for health, dishes/settings/tables, public order idempotency, booking, admin login/session, CSRF rejection, private-path 404 and 100 concurrent orders preserving all commits.
- [ ] **Step 2: Run baseline tests** with `python -m pytest tests/test_legacy_regression.py -q`; expected: current behavior is captured, and any environment-only failures are fixed in fixtures rather than product behavior.
- [ ] **Step 3: Add `pytest>=8,<9` to `requirements.txt`** and make the test fixture launch the server on an ephemeral local port with a temporary private directory.
- [ ] **Step 4: Re-run** `python -m pytest tests/test_legacy_regression.py -q`; expected: PASS.
- [ ] **Step 5: Commit** `test: capture Bosfor legacy regression baseline`.

### Task 2: Database module and versioned migration runner

**Files:**
- Create: `bosfor/__init__.py`
- Create: `bosfor/db.py`
- Create: `bosfor/migrations.py`
- Create: `tests/test_migrations.py`
- Modify: `server.py`

**Interfaces:**
- Produces: `connect(db_path: Path) -> sqlite3.Connection`, `transaction(con) -> ContextManager[sqlite3.Connection]`, `current_schema_version(con) -> int`, `apply_migrations(con) -> list[int]`.
- `server.py` must call `apply_migrations()` from `init_db()` and progressively delegate `db()` to `bosfor.db.connect()`.

- [ ] **Step 1: Write failing tests** asserting `schema_migrations` creation, monotonic migration application, re-run idempotency, `foreign_keys=1`, WAL mode and busy timeout on every fixture connection.
- [ ] **Step 2: Run** `python -m pytest tests/test_migrations.py -q`; expected: FAIL because module/functions do not exist.
- [ ] **Step 3: Implement** `bosfor/db.py` and `bosfor/migrations.py`; first migration records the current schema as the compatibility baseline without destroying existing data.
- [ ] **Step 4: Run migration + legacy tests**; expected: PASS.
- [ ] **Step 5: Commit** `feat: add transactional schema migration foundation`.

### Task 3: Named staff, roles and permissions schema/domain

**Files:**
- Create: `bosfor/auth.py`
- Create: `tests/test_rbac.py`
- Modify: `bosfor/migrations.py`
- Modify: `server.py`

**Interfaces:**
- Produces: `authenticate(con, username: str, password: str) -> StaffPrincipal | None`, `create_session(principal_id: int) -> SessionTokens`, `resolve_session(token: str | None) -> StaffPrincipal | None`, `has_permission(principal, permission: str) -> bool`, `require_permission(principal, permission: str) -> None`.
- Roles: `owner`, `manager`, `cashier`, `waiter`, `kitchen`, `courier`.

- [ ] **Step 1: Write failing tests** for owner bootstrap, password hashing/verification, disabled account denial, permission matrix and role-change effect.
- [ ] **Step 2: Run** `python -m pytest tests/test_rbac.py -q`; expected: FAIL.
- [ ] **Step 3: Add migration** for `staff_users`, `roles`, `role_permissions`, `staff_roles`, `staff_sessions`; seed exact role permissions from the spec and migrate the existing admin password into an owner bootstrap account.
- [ ] **Step 4: Implement auth interfaces** and bridge old `/api/admin/login`, `/api/admin/session`, `/api/admin/logout` to owner-compatible sessions.
- [ ] **Step 5: Run RBAC + legacy tests**; expected: PASS.
- [ ] **Step 6: Commit** `feat: add staff accounts and server-enforced RBAC`.

### Task 4: Stable admin API authorization and error envelope

**Files:**
- Create: `bosfor/http_api.py`
- Create: `tests/test_admin_api_security.py`
- Modify: `server.py`

**Interfaces:**
- Produces: `json_error(code: str, message: str, status: int, details: dict | None = None) -> dict`, `authorize_request(handler, permission: str, csrf: bool = True) -> StaffPrincipal`.
- New endpoint prefix: `/api/admin/v1/*`.

- [ ] **Step 1: Write failing tests** for 401 unauthenticated, 403 insufficient role, 403 invalid CSRF, 415 wrong content type, 413 oversize body, and stable `{ok:false,error:{code,message}}` shape.
- [ ] **Step 2: Run** targeted tests; expected: FAIL.
- [ ] **Step 3: Implement shared request authorization/error helpers** and one smoke endpoint `/api/admin/v1/me` returning safe principal/permissions.
- [ ] **Step 4: Run security + legacy tests**; expected: PASS.
- [ ] **Step 5: Commit** `feat: standardize authenticated admin API layer`.

### Task 5: Immutable audit log

**Files:**
- Create: `bosfor/audit.py`
- Create: `tests/test_audit.py`
- Modify: `bosfor/migrations.py`
- Modify: `server.py`

**Interfaces:**
- Produces: `record_event(con, *, actor_id: int | None, action: str, entity_type: str, entity_id: str | None, reason: str | None, metadata: dict) -> int`, `list_events(con, filters: AuditFilters) -> list[AuditEvent]`.

- [ ] **Step 1: Write failing tests** that successful login/logout, failed login, menu price update and settings change emit audit rows; direct update/delete of audit rows is not exposed by APIs.
- [ ] **Step 2: Run** tests; expected: FAIL.
- [ ] **Step 3: Add `audit_events` migration and implement append-only recording/listing**; wire existing sensitive operations first.
- [ ] **Step 4: Run audit + full baseline suite**; expected: PASS.
- [ ] **Step 5: Commit** `feat: add immutable operational audit trail`.

### Task 6: Phase 1 release gate

**Files:**
- Modify: `README_PRODUCTION.md`
- Create: `docs/PHASE1_FOUNDATION_QA.md`

**Interfaces:**
- Produces: documented bootstrap/login/RBAC/migration behavior for Phase 2.

- [ ] **Step 1: Run** `python -m pytest tests/test_legacy_regression.py tests/test_migrations.py tests/test_rbac.py tests/test_admin_api_security.py tests/test_audit.py -q`.
- [ ] **Step 2: Run SQLite checks** `PRAGMA integrity_check; PRAGMA foreign_key_check;` against a migrated copy of the existing DB; expected: `ok` and zero FK rows.
- [ ] **Step 3: Restart server twice** against the same migrated DB and verify current schema version/data remain stable.
- [ ] **Step 4: Document results** in `docs/PHASE1_FOUNDATION_QA.md`.
- [ ] **Step 5: Commit** `docs: record phase 1 foundation QA gate`.
