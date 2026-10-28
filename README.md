# Wattprint backend

FastAPI + PostgreSQL/TimescaleDB, with [Better Auth](https://better-auth.com/docs/integrations/expo) for Expo clients.

## Architecture

| Service | Stack | Port | Role |
|---|---|---|---|
| `api` | FastAPI, SQLAlchemy 2 async, Alembic | 8000 | Business API (`/api/v1`, OpenAPI at `/docs`) |
| `auth` | Node, Hono, Better Auth (+ `expo`, `bearer` plugins) | 3000 | Sign-up/in, sessions (`/api/auth/*`) |
| `db` | TimescaleDB on PG17 | 5433 | `public` schema = FastAPI, `auth` schema = Better Auth |

Better Auth is JS-only, so it runs as its own service. FastAPI validates each request by forwarding the
`Cookie` / `Authorization: Bearer` header to `GET /api/auth/get-session` (see `backend/app/core/security.py`)
and exposes it as the `CurrentUser` dependency.

## Run

```bash
cp .env.example .env   # set POSTGRES_PASSWORD and BETTER_AUTH_SECRET
docker compose up --build
```

- API docs: http://localhost:8000/docs
- `GET /api/v1/health`, `GET /api/v1/me` (needs a session)

## Expo client

Set `BETTER_AUTH_URL` to an address the device can reach (LAN IP, not `localhost`, on a physical device) and
`EXPO_APP_SCHEMES` to your app scheme (`scheme` in `app.json`). Client setup: `createAuthClient` with
`expoClient({ scheme, storage: SecureStore })` and `baseURL` = the auth URL. Send
`authClient.getCookie()` as the `Cookie` header (or the bearer token) when calling FastAPI.

## Layout

```
backend/   app/{core,db,api,modules}, alembic/, tests/, pyproject.toml (uv)
auth/      src/{auth,index,migrate}.ts
database/  init/*.sql   (run on first DB start)
```

Migrations: `docker compose exec api alembic revision --autogenerate -m "msg"`. Tests: `docker compose exec api pytest`.

## TODO

- Social providers, email verification, OpenAPI 3.2 spec tuning
- Hypertables/continuous aggregates for time-series data
- CI, `uv.lock`, auth service production build (`tsc`)
