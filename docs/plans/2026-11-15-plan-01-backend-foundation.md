# ClassFlow Phase 1 — Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running FastAPI backend with PostgreSQL, migrations, Auth0 token
authentication, users with roles, and an append-only audit log — the base
every later phase builds on.

**Architecture:** Modular monolith in `src/classflow_fastapi/`. Each module
(`accounts`, `audit`) splits router (HTTP) → service (business rules) →
repository/models (DB). Sync SQLAlchemy 2.x sessions with one transaction per
request: services never commit; the `get_db` dependency commits on success and
rolls back on error, so audit entries are atomic with the action they record.

**Tech Stack:** Python 3.14, uv, FastAPI, pydantic-settings, SQLAlchemy 2.x
(sync) + psycopg 3, Alembic, PyJWT[crypto], PostgreSQL 17 (Docker Compose),
pytest + httpx.

**Spec:** `docs/plans/2026-11-15-classflow-mvp-design.md`

## Roadmap (one plan per phase; each later plan is written when the previous lands)

1. **Backend foundation** — this plan.
2. **Timetable** — class types, weekly schedules, session generation, no-overlap rule, public timetable API.
3. **Booking core** — capacity locking, holds, cancellation rules, duplicate prevention (payment behind an interface).
4. **Payments & worker** — Stripe Checkout (card + MobilePay), webhooks, refunds, Postgres job table + worker.
5. **Waitlist & email notifications.**
6. **Attendance, admin exceptions, CSV export.**
7. **Next.js frontend** — may start after phase 2 and run alongside 3–6.
8. **Deployment** — VPS, Docker Compose, TLS, backups.

## Global Constraints

- Python `>=3.14`; run everything via `uv run`; add deps only with `uv add`. Never call `pip`.
- New runtime deps for this phase, and no others: `sqlalchemy`, `alembic`, `psycopg[binary]`, `pyjwt[crypto]`.
- Primary keys are `uuid.UUID` (server-generated `gen_random_uuid()`).
- All datetimes are timezone-aware, stored as `timestamptz`, in UTC.
- Never log access tokens, secrets or Authorization headers.
- The server never trusts client-provided identity or roles; roles come only from the `user_roles` table.
- Roles stored in DB: `instructor`, `admin`. Every authenticated, non-deleted user is implicitly a member.
- Audit entries require a non-blank reason and are append-only (DB-enforced).
- Services do not call `commit()`; transaction boundaries belong to `get_db` (requests) and the CLI.
- Settings come from env vars with prefix `CLASSFLOW_` (and `.env` in dev).
- Commits: CLAUDE.md requires explicit approval to commit. The user approves committing per execution run before the run starts; if not approved, skip the commit steps and leave changes staged.
- Before each commit: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest` all pass.

## Review Focus

1. **Two first requests from a brand-new user arrive at once** → exactly one `users` row is created, and neither request errors. Test in Task 4.
2. **Two admins revoke each other's admin role concurrently** (or the last admin revokes themself) → at least one admin always remains; the losing request gets 409. Test in Task 4.
3. **A token that's expired, has the wrong audience/issuer, uses `alg=none`/HS256, or is missing the email claim** → 401, never a created user. Test in Task 5.
4. **A deleted (anonymised) user presents a still-valid token** → 403, and no new user row is created for that `sub`. Test in Task 5.
5. **Someone tries to edit or delete an audit row directly in SQL** → the database refuses. Test in Task 3.

---

## File Structure

```
compose.yaml                         # Postgres 17 for dev (db classflow) + tests (db classflow_test), port 5433
docker/initdb/01-test-db.sql         # CREATE DATABASE classflow_test;
.env.example                         # all CLASSFLOW_* vars with dev values
alembic.ini
migrations/env.py                    # uses sqlalchemy.url from config, else Settings.database_url
migrations/script.py.mako
migrations/versions/0001_audit_log.py
migrations/versions/0002_users_roles.py
src/classflow_fastapi/
  __init__.py                        # app = create_app(); main() runs uvicorn
  app.py                             # create_app()
  config.py                          # Settings, get_settings()
  db.py                              # Base, engine/session factory, get_db()
  health.py                          # GET /health
  audit/__init__.py
  audit/models.py                    # AuditEntry
  audit/service.py                   # record_audit(), list_audit()
  audit/router.py                    # GET /admin/audit
  accounts/__init__.py
  accounts/models.py                 # Role, User, UserRole
  accounts/service.py                # user creation, role grant/revoke, errors
  accounts/auth.py                   # TokenClaims, TokenVerifier, dependencies
  accounts/router.py                 # /me, /admin/users...
  accounts/cli.py                    # classflow-admin grant-admin
tests/
  conftest.py                        # test DB, migrations, per-test rollback session, client
  helpers/__init__.py
  helpers/tokens.py                  # RSA key + token factory for tests
  test_health.py
  test_db.py
  audit/test_audit_service.py
  audit/test_audit_router.py
  accounts/test_service.py
  accounts/test_auth.py
  accounts/test_router.py
  accounts/test_cli.py
```

Delete: `src/test.py`.

---

### Task 1: Repair the scaffold — app factory, health endpoint, entry point

**Files:**
- Create: `src/classflow_fastapi/app.py`, `src/classflow_fastapi/health.py`, `tests/test_health.py`
- Modify: `src/classflow_fastapi/__init__.py` (currently fails to import: decorator over-indented)
- Delete: `src/test.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI` in `classflow_fastapi.app`; `classflow_fastapi.app` module-level `app` re-exported from `classflow_fastapi.__init__`; `main() -> None` in `classflow_fastapi.__init__` (runs `uvicorn.run("classflow_fastapi:app", host="0.0.0.0", port=8000)`). `create_app()` must not read settings at call time (settings are read inside dependencies), so importing the package works without env vars.

- [ ] **Step 1: Write the failing test** `tests/test_health.py`

```python
from fastapi.testclient import TestClient
from classflow_fastapi.app import create_app

def test_health_returns_healthy():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
```

- [ ] **Step 2: Run** `uv run pytest tests/test_health.py -v` — Expected: FAIL (`ModuleNotFoundError: classflow_fastapi.app` / IndentationError).
- [ ] **Step 3: Implement** `health.py` (APIRouter with `HealthCheckResponse(status: str)` and `GET /health`), `app.py` (`create_app()` titled "ClassFlow API", includes health router), rewrite `__init__.py` to `from classflow_fastapi.app import create_app; app = create_app()` plus `main()`. Delete `src/test.py`.
- [ ] **Step 4: Run** `uv run pytest tests/test_health.py -v` — Expected: PASS. Also `uv run python -c "import classflow_fastapi"` exits 0.
- [ ] **Step 5: Commit** — `fix: repair app import and add app factory with health endpoint`

---

### Task 2: Settings, Postgres, SQLAlchemy, Alembic and test database fixtures

**Files:**
- Create: `compose.yaml`, `docker/initdb/01-test-db.sql`, `.env.example`, `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `src/classflow_fastapi/config.py`, `src/classflow_fastapi/db.py`, `tests/conftest.py`, `tests/test_db.py`
- Modify: `pyproject.toml` (via `uv add sqlalchemy alembic "psycopg[binary]" "pyjwt[crypto]"`), `.gitignore` (add `.env`)

**Interfaces:**
- Produces:
  - `Settings(BaseSettings)` with `database_url: str`, `auth0_domain: str`, `auth0_audience: str`, `auth0_claims_namespace: str = "https://classflow/"`; `env_prefix="CLASSFLOW_"`, `env_file=".env"`. `get_settings() -> Settings` (`lru_cache`).
  - `Base(DeclarativeBase)` with a `MetaData(naming_convention=...)` (ix/uq/ck/fk/pk conventions).
  - `get_engine() -> Engine` (`lru_cache`, from settings), `get_db() -> Iterator[Session]`: yields a session, commits on success, rolls back on exception, always closes.
  - Test fixtures in `tests/conftest.py`: `engine` (session-scoped; URL from env `CLASSFLOW_TEST_DATABASE_URL`, default `postgresql+psycopg://classflow:classflow@localhost:5433/classflow_test`; drops and recreates schema `public`, then runs `alembic upgrade head` programmatically with `sqlalchemy.url` set), `db` (function-scoped `Session` bound to a connection inside an outer transaction with `join_transaction_mode="create_savepoint"`, rolled back after the test), `client` (TestClient of `create_app()` with `get_db` overridden to yield `db`).
- `compose.yaml`: service `postgres`, image `postgres:17`, env `POSTGRES_USER=classflow`, `POSTGRES_PASSWORD=classflow`, `POSTGRES_DB=classflow`, port `5433:5432`, volume for data, `./docker/initdb` mounted at `/docker-entrypoint-initdb.d`.
- `.env.example`: `CLASSFLOW_DATABASE_URL=postgresql+psycopg://classflow:classflow@localhost:5433/classflow`, `CLASSFLOW_AUTH0_DOMAIN=your-tenant.eu.auth0.com`, `CLASSFLOW_AUTH0_AUDIENCE=https://api.classflow`, `CLASSFLOW_AUTH0_CLAIMS_NAMESPACE=https://classflow/`.
- `migrations/env.py`: `target_metadata = Base.metadata` after importing all model modules (`classflow_fastapi.audit.models`, `classflow_fastapi.accounts.models` — add each as its task creates it); URL = `config.get_main_option("sqlalchemy.url")` or `get_settings().database_url`.

- [ ] **Step 1: Start Postgres** — `docker compose up -d postgres`; Expected: `docker compose ps` shows it healthy/running.
- [ ] **Step 2: Write the failing test** `tests/test_db.py`

```python
from sqlalchemy import text

def test_database_reachable(db):
    assert db.execute(text("SELECT 1")).scalar_one() == 1
    assert db.execute(text("SELECT current_database()")).scalar_one() == "classflow_test"
```

- [ ] **Step 3: Run** `uv run pytest tests/test_db.py -v` — Expected: FAIL (fixture `db` not found).
- [ ] **Step 4: Implement** the dependencies, config, db, alembic setup and conftest fixtures above. `alembic.ini` sets `script_location = migrations`.
- [ ] **Step 5: Run** `uv run pytest -v` — Expected: both tests PASS. Also `uv run alembic upgrade head` against the dev DB exits 0 (with `.env` copied from `.env.example`).
- [ ] **Step 6: Commit** — `feat: add settings, PostgreSQL, SQLAlchemy and Alembic with test fixtures`

---

### Task 3: Append-only audit log

**Files:**
- Create: `src/classflow_fastapi/audit/__init__.py`, `audit/models.py`, `audit/service.py`, `migrations/versions/0001_audit_log.py`, `tests/audit/__init__.py`, `tests/audit/test_audit_service.py`
- Modify: `migrations/env.py` (import audit models)

**Interfaces:**
- Produces:
  - `AuditEntry` table `audit_log`: `id UUID pk`, `created_at timestamptz default now()`, `actor_user_id UUID NULL` (NULL = system/CLI; FK to `users` added in migration 0002), `action text NOT NULL` (e.g. `"role.granted"`), `target_type text NOT NULL`, `target_id text NOT NULL`, `reason text NOT NULL` with `CHECK (length(btrim(reason)) > 0)`, `details jsonb NULL`. Index on `created_at`.
  - `record_audit(db: Session, *, actor_id: UUID | None, action: str, target_type: str, target_id: str, reason: str, details: dict[str, Any] | None = None) -> AuditEntry` — raises `ValueError("reason is required")` for blank reason; adds + flushes, never commits.
  - `list_audit(db: Session, *, limit: int = 50, before: datetime | None = None) -> list[AuditEntry]` — newest first.
- Migration 0001 also creates a trigger function `audit_log_immutable()` that `RAISE EXCEPTION 'audit_log is append-only'`, attached `BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW`.

- [ ] **Step 1: Write the failing tests** `tests/audit/test_audit_service.py`

```python
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from classflow_fastapi.audit.service import record_audit, list_audit

def test_record_audit_persists_entry(db):
    entry = record_audit(db, actor_id=None, action="role.granted", target_type="user",
                         target_id="abc", reason="bootstrap", details={"role": "admin"})
    assert entry.id is not None
    assert list_audit(db)[0].id == entry.id
    assert list_audit(db)[0].details == {"role": "admin"}

@pytest.mark.parametrize("reason", ["", "   "])
def test_record_audit_rejects_blank_reason(db, reason):
    with pytest.raises(ValueError, match="reason is required"):
        record_audit(db, actor_id=None, action="x", target_type="t", target_id="1", reason=reason)

def test_list_audit_newest_first_and_limit(db):
    for i in range(3):
        record_audit(db, actor_id=None, action=f"a{i}", target_type="t", target_id=str(i), reason="r")
        db.execute(text("SELECT pg_sleep(0.01)"))
    assert [e.action for e in list_audit(db, limit=2)] == ["a2", "a1"]

@pytest.mark.parametrize("sql", ["UPDATE audit_log SET reason = 'changed'", "DELETE FROM audit_log"])
def test_audit_rows_cannot_be_changed(db, sql):
    record_audit(db, actor_id=None, action="x", target_type="t", target_id="1", reason="r")
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin_nested():
            db.execute(text(sql))
```

Note: `created_at` uses `now()` (transaction start time), so in `test_list_audit_newest_first_and_limit` all rows share a transaction; use `clock_timestamp()` as the column default so ordering is real, and order by `created_at DESC, id DESC`.

- [ ] **Step 2: Run** `uv run pytest tests/audit -v` — Expected: FAIL (module not found).
- [ ] **Step 3: Implement** model, migration 0001 (`down_revision=None`, default `clock_timestamp()`), and service.
- [ ] **Step 4: Run** `uv run pytest tests/audit -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: add append-only audit log`

---

### Task 4: Users, roles and the accounts service

**Files:**
- Create: `src/classflow_fastapi/accounts/__init__.py`, `accounts/models.py`, `accounts/service.py`, `migrations/versions/0002_users_roles.py`, `tests/accounts/__init__.py`, `tests/accounts/test_service.py`
- Modify: `migrations/env.py` (import accounts models)

**Interfaces:**
- Consumes: `record_audit(...)` (Task 3), `Base` (Task 2).
- Produces:
  - `class Role(StrEnum): INSTRUCTOR = "instructor"; ADMIN = "admin"`.
  - `User` table `users`: `id UUID pk`, `auth0_sub text UNIQUE NOT NULL`, `email text NOT NULL`, `name text NOT NULL`, `phone text NULL`, `created_at timestamptz`, `deleted_at timestamptz NULL`. Relationship `roles` → `UserRole`. Property `role_set -> set[Role]`.
  - `UserRole` table `user_roles`: `user_id UUID FK users ON DELETE CASCADE`, `role text CHECK IN ('instructor','admin')`, PK `(user_id, role)`, `granted_at timestamptz`.
  - Migration 0002 also adds FK `audit_log.actor_user_id → users.id`.
  - `@dataclass(frozen=True) class TokenClaims: sub: str; email: str; name: str` (defined here in `accounts/service.py`; Task 5 builds it from the JWT).
  - `get_or_create_user(db: Session, claims: TokenClaims) -> User` — `INSERT ... ON CONFLICT (auth0_sub) DO NOTHING` then select; if the existing user's email differs from the claim and the user isn't deleted, update email. Name is set only on creation (later editable by the member in a future phase).
  - `grant_role(db: Session, *, actor_id: UUID | None, user_id: UUID, role: Role, reason: str) -> None` — idempotent: granting an existing role is a no-op with no audit entry; otherwise inserts + `record_audit(action="role.granted", target_type="user", target_id=str(user_id), details={"role": role})`. Raises `UserNotFoundError` for unknown or deleted user.
  - `revoke_role(db: Session, *, actor_id: UUID | None, user_id: UUID, role: Role, reason: str) -> None` — no-op if not held. For `Role.ADMIN`, first `SELECT ... FROM user_roles WHERE role='admin' FOR UPDATE` (locks all admin rows), and if this is the last admin raise `LastAdminError`. Audits `role.revoked`.
  - `find_user_by_email(db: Session, email: str) -> User | None` (case-insensitive, excludes deleted).
  - `list_users(db: Session, *, search: str | None = None, limit: int = 50) -> list[User]` — case-insensitive match on name/email, excludes deleted, ordered by name.
  - Exceptions in `accounts/service.py`: `UserNotFoundError`, `LastAdminError`.

- [ ] **Step 1: Write the failing tests** `tests/accounts/test_service.py`

```python
def test_get_or_create_user_creates_once(db):
    claims = TokenClaims(sub="auth0|1", email="a@example.com", name="Anna")
    first = get_or_create_user(db, claims)
    second = get_or_create_user(db, claims)
    assert first.id == second.id
    assert first.role_set == set()

def test_get_or_create_user_updates_changed_email(db):
    get_or_create_user(db, TokenClaims(sub="auth0|1", email="old@example.com", name="Anna"))
    user = get_or_create_user(db, TokenClaims(sub="auth0|1", email="new@example.com", name="Other"))
    assert user.email == "new@example.com"
    assert user.name == "Anna"

def test_grant_role_audits_once_and_is_idempotent(db): ...
    # grant ADMIN twice -> role_set == {Role.ADMIN}; exactly one audit entry with action "role.granted"

def test_grant_role_unknown_user_raises(db): ...
    # uuid4() -> UserNotFoundError

def test_revoke_last_admin_raises(db): ...
    # single admin revokes own ADMIN -> LastAdminError; role still held

def test_revoke_admin_when_another_admin_exists(db): ...
    # two admins; revoke one -> succeeds, audit "role.revoked"

def test_list_users_search_excludes_deleted(db): ...
    # users "Anna", "Bo", deleted "Anne" -> search "an" returns ["Anna"]
```

Concurrency tests use committed data, so add a `committed_engine` fixture in `tests/conftest.py` that yields the engine and afterwards runs `TRUNCATE audit_log, user_roles, users CASCADE`:

```python
def test_concurrent_first_requests_create_one_user(committed_engine):
    claims = TokenClaims(sub="auth0|race", email="r@example.com", name="R")
    def attempt(_):
        with Session(committed_engine) as s, s.begin():
            return get_or_create_user(s, claims).id
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = set(pool.map(attempt, range(8)))
    assert len(ids) == 1

def test_concurrent_admin_revokes_keep_one_admin(committed_engine):
    # create admins A and B (committed). In two threads: A revokes B, B revokes A,
    # synchronised with a threading.Barrier before calling revoke_role.
    # Assert: exactly one thread raised LastAdminError, and exactly one admin remains.
```

- [ ] **Step 2: Run** `uv run pytest tests/accounts/test_service.py -v` — Expected: FAIL (import errors).
- [ ] **Step 3: Implement** models, migration 0002 (`down_revision="0001"`), service.
- [ ] **Step 4: Run** `uv run pytest tests/accounts/test_service.py -v` — Expected: PASS (run 3 times; concurrency tests must pass every time).
- [ ] **Step 5: Commit** — `feat: add users, roles and accounts service`

---

### Task 5: Auth0 token verification, current user, role guards, `GET /me`

**Files:**
- Create: `src/classflow_fastapi/accounts/auth.py`, `accounts/router.py` (with `/me` only for now), `tests/helpers/__init__.py`, `tests/helpers/tokens.py`, `tests/accounts/test_auth.py`
- Modify: `src/classflow_fastapi/app.py` (include accounts router), `tests/conftest.py` (verifier override)

**Interfaces:**
- Consumes: `TokenClaims`, `get_or_create_user` (Task 4), `get_settings`, `get_db` (Task 2).
- Produces:
  - `class InvalidTokenError(Exception)`.
  - `class TokenVerifier: __init__(self, *, issuer: str, audience: str, claims_namespace: str, key_resolver: Callable[[str], Any])`; `verify(self, token: str) -> TokenClaims` — `jwt.decode(token, key_resolver(token), algorithms=["RS256"], audience=..., issuer=..., options={"require": ["exp", "iss", "aud", "sub"]})`; email from `f"{ns}email"`, name from `f"{ns}name"` (fallback: email). Any PyJWT error, resolver error, or missing email → `InvalidTokenError`. Never logs the token.
  - `get_token_verifier() -> TokenVerifier` (`lru_cache`): issuer `f"https://{settings.auth0_domain}/"`, resolver uses `PyJWKClient(f"https://{settings.auth0_domain}/.well-known/jwks.json", cache_keys=True).get_signing_key_from_jwt(token).key`.
  - `get_current_user(credentials = Depends(HTTPBearer(auto_error=False)), verifier = Depends(get_token_verifier), db = Depends(get_db)) -> User` — no/invalid token → 401 with `WWW-Authenticate: Bearer`; deleted user (`deleted_at` set) → 403. A deleted user is matched by `auth0_sub`, so no new row is created.
  - `require_role(role: Role) -> Callable[..., User]` — dependency factory; 403 if role not held.
  - `GET /me` → `MeResponse { id: UUID, email: str, name: str, phone: str | None, roles: list[Role] }` (roles sorted).
  - Test helpers `tests/helpers/tokens.py`: `TEST_ISSUER = "https://test.auth0.local/"`, `TEST_AUDIENCE = "https://api.classflow.test"`, `TEST_NS = "https://classflow/"`; `make_token(*, sub="auth0|1", email="a@example.com", name="Anna", exp_delta=timedelta(minutes=5), audience=TEST_AUDIENCE, issuer=TEST_ISSUER, key=TEST_PRIVATE_KEY, algorithm="RS256", extra=None) -> str`; `test_verifier() -> TokenVerifier` using the matching public key. `conftest.client` overrides `get_token_verifier` with `test_verifier()`. Auth0 setup note: an Auth0 post-login Action must add `https://classflow/email` and `https://classflow/name` to the access token (document in README, Task 7).

- [ ] **Step 1: Write the failing tests** `tests/accounts/test_auth.py`

```python
def test_me_creates_user_from_token(client):
    r = client.get("/me", headers={"Authorization": f"Bearer {make_token()}"})
    assert r.status_code == 200
    assert r.json()["email"] == "a@example.com" and r.json()["roles"] == []

def test_me_without_token_is_401(client):
    r = client.get("/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"

@pytest.mark.parametrize("token_kwargs", [
    {"exp_delta": timedelta(seconds=-10)},
    {"audience": "https://wrong"},
    {"issuer": "https://evil.example/"},
    {"key": OTHER_PRIVATE_KEY},
    {"email": None},
])
def test_invalid_tokens_are_401_and_create_no_user(client, db, token_kwargs):
    r = client.get("/me", headers={"Authorization": f"Bearer {make_token(**token_kwargs)}"})
    assert r.status_code == 401
    assert db.scalar(select(func.count()).select_from(User)) == 0

def test_hs256_token_signed_with_public_key_is_rejected(client): ...
    # algorithm-confusion attempt: HS256 token using the PEM public key bytes as secret -> 401

def test_garbage_token_is_401(client): ...   # "Bearer not-a-jwt" -> 401

def test_deleted_user_is_403_and_not_recreated(client, db): ...
    # call /me once, set user.deleted_at, flush; call again -> 403; count users == 1

def test_require_role_admin(client, db): ...
    # mount a throwaway route in the test app: Depends(require_role(Role.ADMIN));
    # member -> 403; after grant_role ADMIN -> 200
```

`OTHER_PRIVATE_KEY` is a second RSA key in `tests/helpers/tokens.py`. `make_token(email=None)` omits the email claim.

- [ ] **Step 2: Run** `uv run pytest tests/accounts/test_auth.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `auth.py`, `/me` in `router.py`, wire into `create_app()`, test helpers + conftest override.
- [ ] **Step 4: Run** `uv run pytest -v` — Expected: all PASS.
- [ ] **Step 5: Commit** — `feat: verify Auth0 access tokens and expose current user`

---

### Task 6: Admin endpoints — users, roles, audit log

**Files:**
- Create: `src/classflow_fastapi/audit/router.py`, `tests/accounts/test_router.py`, `tests/audit/test_audit_router.py`
- Modify: `src/classflow_fastapi/accounts/router.py`, `src/classflow_fastapi/app.py`

**Interfaces:**
- Consumes: `require_role`, `get_current_user` (Task 5); `list_users`, `grant_role`, `revoke_role`, `UserNotFoundError`, `LastAdminError` (Task 4); `list_audit` (Task 3).
- Produces (all require `Role.ADMIN`):
  - `GET /admin/users?search=&limit=50` → `list[UserSummary { id, email, name, roles }]`.
  - `POST /admin/users/{user_id}/roles` body `RoleChange { role: Role, reason: str (min_length=1, stripped) }` → 204. Unknown user → 404.
  - `POST /admin/users/{user_id}/roles/revoke` body `RoleChange` → 204. Last admin → 409 `{"detail": "Cannot remove the last admin"}`. Unknown user → 404.
  - `GET /admin/audit?limit=50&before=<iso datetime>` (limit 1–200) → `list[AuditEntryOut { id, created_at, actor_user_id, action, target_type, target_id, reason, details }]`.
  - Blank reason → 422 (pydantic validation).

- [ ] **Step 1: Write the failing tests**

```python
# tests/accounts/test_router.py — helper: admin_headers(client, db) logs in sub "auth0|admin" via /me, grants ADMIN with actor None
def test_member_cannot_list_users(client): ...                    # 403
def test_admin_lists_users_with_search(client, db): ...           # search "ann" -> only Anna
def test_admin_grants_instructor_and_it_is_audited(client, db): ... # 204; /me of target shows ["instructor"]; GET /admin/audit[0].action == "role.granted", reason as sent
def test_grant_requires_reason(client, db): ...                   # reason "  " -> 422
def test_grant_unknown_user_404(client, db): ...
def test_admin_cannot_revoke_last_admin(client, db): ...          # 409, detail "Cannot remove the last admin"

# tests/audit/test_audit_router.py
def test_audit_requires_admin(client): ...                        # member -> 403
def test_audit_pagination_with_before(client, db): ...            # 3 entries; limit=2 -> newest 2; before=<2nd.created_at> -> oldest 1
```

- [ ] **Step 2: Run** `uv run pytest tests/accounts/test_router.py tests/audit/test_audit_router.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** endpoints and error mapping (service exceptions → HTTPException in routers only).
- [ ] **Step 4: Run** `uv run pytest -v` — Expected: all PASS.
- [ ] **Step 5: Commit** — `feat: add admin endpoints for users, roles and audit log`

---

### Task 7: Bootstrap-admin CLI and developer docs

**Files:**
- Create: `src/classflow_fastapi/accounts/cli.py`, `tests/accounts/test_cli.py`
- Modify: `pyproject.toml` (`[project.scripts]` add `classflow-admin = "classflow_fastapi.accounts.cli:main"`; keep `classflow-fastapi = "classflow_fastapi:main"`), `README.md`, `CLAUDE.md` (Commands: add `docker compose up -d postgres`, `uv run alembic upgrade head`, `uv run classflow-admin grant-admin --email ...`; Architecture: frontend line stays Next.js)

**Interfaces:**
- Consumes: `find_user_by_email`, `grant_role` (Task 4), `get_engine` (Task 2).
- Produces: `main(argv: list[str] | None = None, *, engine: Engine | None = None) -> int` — argparse subcommand `grant-admin --email EMAIL`. Opens its own transaction (`with Session(engine) as s, s.begin()`). Success: grants ADMIN with `actor_id=None`, `reason="bootstrap via CLI"`, prints `Granted admin to <email>`, returns 0. Unknown email: prints to stderr `No user with email <email>. Log in to ClassFlow once first.`, returns 1.

- [ ] **Step 1: Write the failing tests** `tests/accounts/test_cli.py` (use `committed_engine`, `capsys`)

```python
def test_grant_admin_existing_user(committed_engine, capsys): ...
    # create user (committed) -> main(["grant-admin", "--email", "A@Example.com"], engine=committed_engine) == 0
    # role_set == {Role.ADMIN}; audit entry actor_user_id is None, reason "bootstrap via CLI"

def test_grant_admin_unknown_email(committed_engine, capsys): ...
    # returns 1; stderr contains "Log in to ClassFlow once first."
```

- [ ] **Step 2: Run** `uv run pytest tests/accounts/test_cli.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `cli.py`; update `pyproject.toml` scripts; `uv sync`.
- [ ] **Step 4: Write README** sections: prerequisites (Docker, uv), local setup (`cp .env.example .env`, `docker compose up -d postgres`, `uv sync`, `uv run alembic upgrade head`, `uv run fastapi dev src/classflow_fastapi/__init__.py`), Auth0 setup (API with audience = `CLASSFLOW_AUTH0_AUDIENCE`, RS256; post-login Action adding `https://classflow/email` and `https://classflow/name` claims to the access token), first admin (`uv run classflow-admin grant-admin --email you@example.com` after first login), running tests. Update CLAUDE.md commands.
- [ ] **Step 5: Run full verification** — `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest -v`. Expected: all clean/PASS.
- [ ] **Step 6: Commit** — `feat: add bootstrap admin CLI and developer setup docs`
