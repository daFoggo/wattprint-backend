# Restructure to FastAPI "Bigger Applications" Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `backend/app` to the layout from the FastAPI "Bigger Applications" tutorial, with the FastAPI-native JWT auth (replacing the previous external auth service) working end to end in Docker.

**Architecture:** Flat `app/` package: `main.py`, `dependencies.py`, `routers/`, plus `models/`, `schemas/`, `services/` and top-level `config.py`, `database.py`, `security.py`. Routers are modules each exposing `router = APIRouter(prefix=..., tags=[...])`; `main.py` includes them under `/api/v1` using relative imports. Business logic lives in `services/`, routers stay thin.

**Tech Stack:** FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, PyJWT, pwdlib[argon2], pytest-asyncio, TimescaleDB (PG17), Docker Compose.

**Spec:** https://fastapi.tiangolo.com/tutorial/bigger-applications/ and https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/ (plus the user's decision to drop the previous external auth service for FastAPI JWT).

## Global Constraints

- Layout per tutorial: `app/main.py`, `app/dependencies.py`, `app/routers/{health,auth,users}.py`; every router module defines a variable named `router`, and `main.py` imports the modules (`from .routers import auth, health, users`), not the variable.
- Relative imports inside `app/` (`from ..dependencies import CurrentUser`), as in the tutorial.
- Routers carry `prefix` (no trailing `/`) and `tags`; `main.py` adds `prefix="/api/v1"` on include.
- `pyproject.toml` gets `[tool.fastapi] entrypoint = "app.main:app"`.
- Login is OAuth2 password flow at `POST /api/v1/auth/token`; `OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")`.
- JWT: HS256, secret from required env `JWT_SECRET_KEY`, access 15 min, refresh 30 days (single-use, rotated, stored hashed).
- No trace of the previous external auth service (service, env vars, docs).
- Python 3.12, line length 100, `ruff check` clean.

## Review Focus

- Access token signed with a different key is rejected (401).
- Expired access token is rejected (401).
- Token whose `sub` is not a UUID is rejected (401, not 500).
- Inactive user cannot log in (400) and an old access token stops working (400).
- Email case: `A@x.com` and `a@x.com` are the same account (409 on second register).
- App refuses to start without `JWT_SECRET_KEY`.

---

### Task 1: Restructure package and keep behavior identical

**Files:**
- Create: `backend/app/{config,database,security,dependencies}.py`, `backend/app/routers/{__init__,health,auth,users}.py`, `backend/app/models/{__init__,user,refresh_token}.py`, `backend/app/schemas/{__init__,user,token}.py`, `backend/app/services/{__init__,auth}.py`, `backend/tests/test_tokens.py`
- Modify: `backend/app/main.py`, `backend/alembic/env.py`, `backend/pyproject.toml`, `backend/tests/test_api.py` (only if imports change), `docker-compose.yml`
- Delete: `backend/app/core/`, `backend/app/db/`, `backend/app/api/`, `backend/app/modules/`

**Interfaces:**
- Produces (import paths later tasks rely on): `app.config.settings`; `app.database.{Base, engine, get_session}`; `app.security.{hash_password, verify_password, create_access_token, decode_access_token, hash_token, new_refresh_token, DUMMY_HASH}`; `app.dependencies.{DbSession, CurrentUser, oauth2_scheme}`; `app.models.{User, RefreshToken}` (re-exported from `app/models/__init__.py` so `Base.metadata` is complete on `import app.models`); `app.schemas.{UserCreate, UserRead, TokenPair, RefreshRequest}`; `app.services.auth.{register_user, authenticate, issue_tokens, rotate_refresh_token, revoke_refresh_token}`.
- Consumes: the current implementations under `core/`, `db/`, `api/`, `modules/` (move the code, do not rewrite it).

- [ ] **Step 1: Write the review-focus tests** in `backend/tests/test_tokens.py` (use the `client`/`email` fixtures pattern from `test_api.py`; move shared fixtures to `backend/tests/conftest.py`). Tests: `test_token_signed_with_other_key_rejected` (jwt.encode with key `"x"*32`, expect 401), `test_expired_access_token_rejected` (exp in the past), `test_non_uuid_sub_rejected` (sub `"not-a-uuid"` signed with the real key, expect 401), `test_inactive_user_cannot_login_or_use_token` (set `is_active=False` via a `get_session` DB update; login 400, previously issued token 400), `test_email_case_insensitive_conflict` (already in `test_api.py::test_duplicate_email_conflicts`; keep it). Run: `docker compose exec api pytest tests/test_tokens.py -q`. Expected: tests run against the old layout and PASS, which proves they pin current behavior before the move.
- [ ] **Step 2: Move code to the new layout** with `git mv` where a file maps one to one: `core/config.py`→`config.py`, `core/security.py`→`security.py`, `api/deps.py`→`dependencies.py`, `modules/auth/service.py`→`services/auth.py`, `modules/auth/models.py`→`models/refresh_token.py`, `modules/users/models.py`→`models/user.py`, `modules/auth/schemas.py`→`schemas/token.py`, `modules/users/schemas.py`→`schemas/user.py`, `modules/auth/router.py`→`routers/auth.py`, `modules/users/router.py`→`routers/users.py`. Merge `db/base.py` and `db/session.py` into `database.py`. Move the `health` handler out of `api/v1/routes.py` into `routers/health.py` with `router = APIRouter(prefix="/health", tags=["system"])` and `GET ""` (final URL stays `/api/v1/health`; use `@router.get("")`). Rewrite imports to relative form. `models/__init__.py` imports `User` and `RefreshToken`. Delete the now-empty old packages.
- [ ] **Step 3: Rewrite `app/main.py`** to `from .routers import auth, health, users`, create `app = FastAPI(...)` with the existing `openapi_tags`, CORS block unchanged, then `for module in (health, auth, users): app.include_router(module.router, prefix="/api/v1")`.
- [ ] **Step 4: Update wiring.** `backend/alembic/env.py`: `from app import models  # noqa: F401`, `from app.config import settings`, `from app.database import Base`. `backend/pyproject.toml`: add `[tool.fastapi]` with `entrypoint = "app.main:app"`. `docker-compose.yml`: delete the old auth service; in `api` remove `the old auth service URL`, add `JWT_SECRET_KEY: ${JWT_SECRET_KEY}`, keep `DATABASE_URL` and `CORS_ORIGINS`.
- [ ] **Step 5: Run everything.** `docker compose up -d --build`, then `docker compose exec api pytest -q` and `docker compose exec api ruff check app tests`. Expected: all tests PASS (old and new), ruff clean, `curl localhost:8000/api/v1/health` returns `{"status":"ok"}`.
- [ ] **Step 6: Commit** `git add -A && git commit -m "refactor: adopt FastAPI bigger-applications layout, replace the previous external auth service with JWT"`.

### Task 2: Initial Alembic migration

**Files:**
- Create: `backend/alembic/versions/<ts>_initial_users_and_refresh_tokens.py` (generated)
- Test: manual migration round trip (no new test file)

**Interfaces:**
- Consumes: `app.models` metadata from Task 1.

- [ ] **Step 1:** In a clean database (`docker compose down -v && docker compose up -d db`), run `docker compose run --rm api alembic revision --autogenerate -m "initial users and refresh tokens"`. Expected: file creates `users` (unique index on `email`) and `refresh_tokens` (FK to `users.id` with `ON DELETE CASCADE`, unique `token_hash`). Remove the `sa.Enum`/unrelated noise if any; keep it hand-readable.
- [ ] **Step 2:** `docker compose up -d --build`, confirm the api container applied it (`docker compose logs api`), then run `docker compose exec api alembic downgrade base && docker compose exec api alembic upgrade head`. Expected: both succeed, and `docker compose exec api pytest -q` PASSES.
- [ ] **Step 3: Commit** `git add -A && git commit -m "feat: initial migration"`.

### Task 3: Docs, env, push

**Files:**
- Modify: `README.md`, `.env.example`
- Delete: stale references to the previous external auth service (grep the repo)

- [ ] **Step 1:** Rewrite `README.md`: services (`api`, `db`), layout tree (the new one), run instructions, auth flow (`register` → `token` → `refresh` → `logout`, Swagger Authorize), how to add a router (create `app/routers/x.py`, include in `main.py`), migrations and tests commands, TODO (social login via ID-token verification, email verification, hypertables). `.env.example` already carries `JWT_SECRET_KEY`; confirm no leftover variables of the previous external auth service.
- [ ] **Step 2:** Grep the repo for leftover names of the previous external auth service. Expected: no matches.
- [ ] **Step 3: Commit and push** `git add -A && git commit -m "docs: README for FastAPI JWT auth and new layout" && git push origin main`.

---

**Self-review:** Spec coverage: layout, routers with prefix/tags, `dependencies.py`, relative imports, entrypoint, `include_router` prefix are all in Task 1; JWT recipe constraints are in Global Constraints and covered by existing and new tests. `internal/` is intentionally omitted (the tutorial uses it for third-party routers; this project has none). Names match across tasks (`app.models`, `app.database.Base`).
