# Wattprint backend

FastAPI + PostgreSQL/TimescaleDB with FastAPI-native JWT auth (access token + rotating refresh token).

## Services

| Service | Stack | Port | Role |
|---|---|---|---|
| `api` | FastAPI, SQLAlchemy 2 async, Alembic | 8000 | Business API (`/api/v1`, OpenAPI at `/docs`) |
| `db` | TimescaleDB on PG17 | 5433 | Application database |

## Run

```bash
cp .env.example .env
# set POSTGRES_PASSWORD and JWT_SECRET_KEY (empty in .env.example; compose aborts until set)
docker compose up --build
```

`JWT_SECRET_KEY` must be at least 32 characters (enforced at startup) and is intentionally empty in
`.env.example`, so you must set your own. Generate one with:

```bash
openssl rand -hex 32
```

API docs: http://localhost:8000/docs

Note: a database volume created by the earlier Better Auth setup keeps its old `auth` schema. Reset it with
`docker compose down -v` (destroys local data) or `DROP SCHEMA auth CASCADE;` in the database.

## Layout

```
app/
  main.py          entrypoint, includes routers
  config.py        settings (env)
  database.py      async engine, session, Base
  dependencies.py  shared dependencies (db session, current user)
  security.py      password hashing, JWT helpers
  models/          SQLAlchemy models (user, refresh_token)
  schemas/         Pydantic schemas (token, user)
  routers/         auth, health, users
  services/        business logic (auth)
alembic/           migrations (versions/); an early one enables the TimescaleDB extension
tests/
pyproject.toml     (uv)
Dockerfile
docker-compose.yml
```

TimescaleDB: the extension is enabled by the `enable timescaledb` Alembic migration (needs a superuser DB role,
which the compose `db` user is).

## Auth flow

1. `POST /api/v1/auth/register` creates a user.
2. `POST /api/v1/auth/token` (form: username = email, password) returns an access token and a refresh token.
3. Call protected endpoints with `Authorization: Bearer <access_token>`.
4. `POST /api/v1/auth/refresh` exchanges a refresh token for a new pair.
5. `POST /api/v1/auth/logout` revokes the refresh token.

In Swagger (`/docs`) click Authorize and log in with email and password to try protected endpoints.

## Adding a router

1. Create `app/routers/x.py` with an `APIRouter(prefix="/x", tags=["x"])`.
2. Import it in `app/main.py` and add it to the tuple in the `for module in (health, auth, users):` loop,
   which mounts every router under `/api/v1`.

## Migrations and tests

```bash
docker compose exec api alembic revision --autogenerate -m "msg"
docker compose exec api alembic upgrade head
docker compose exec api pytest
```

Tests run inside the `api` container because settings require `JWT_SECRET_KEY` at import time.

## TODO

- Social login (Google/Apple) via server-side ID-token verification
- Email verification
- Hypertables/continuous aggregates for time-series data
- CI
