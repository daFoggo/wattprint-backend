# Wattprint backend

FastAPI + PostgreSQL/TimescaleDB with Keycloak identity service (OIDC, runs in the same compose project).

## Services

| Service | Stack | Port | Role |
|---|---|---|---|
| `api` | FastAPI, SQLAlchemy 2 async, Alembic | 11093 | Business API (`/api/v1`, OpenAPI at `/docs`) |
| `db` | TimescaleDB 2.31 on PostgreSQL 18 | 11096 | Application database |
| `keycloak` | Keycloak 26 (`start-dev`) + its own Postgres (`keycloak-db`) | 11095 | Identity: login, users, roles. Realm `wattprint` is imported from `keycloak/realm/` on first start |

## Run

```bash
cp .env.example .env
# set POSTGRES_PASSWORD, KEYCLOAK_ADMIN_PASSWORD, KEYCLOAK_DB_PASSWORD, WATTPRINT_ADMIN_PASSWORD (empty in .env.example; compose aborts until set)
docker compose up --build
```

The image's default command runs `alembic upgrade head` before starting uvicorn; compose uses a dev command (same migration step, plus `--reload`).

API docs: http://localhost:11093/docs

Keycloak console: http://localhost:11095 (user `admin`, `KEYCLOAK_ADMIN_PASSWORD`).

## Layout

```
app/
  main.py          entrypoint, includes routers
  config.py        settings (env)
  database.py      async engine, session, Base
  dependencies.py  shared dependencies (db session, current user)
  security.py      Keycloak access-token verification (JWKS, RS256)
  models/          SQLAlchemy models
  schemas/         Pydantic schemas (user)
  routers/         health, users
  services/        business logic (users: first-login provisioning)
keycloak/realm/    realm export imported by Keycloak on first start (clients, roles, admin user)
alembic/           hand-written revisions in versions/{public,ai,updates}; database-wide bootstrap revisions stay in versions/
tests/
pyproject.toml     (uv)
Dockerfile
docker-compose.yml
```

The database bootstrap enables TimescaleDB and the foundation revision ensures required extensions and database roles.
Migrations need a database owner with permission to create extensions and roles (the compose `db` user has these permissions).

## Auth flow (Keycloak)

- Sign-in is Google only: the realm's browser flow `browser-google` redirects straight to the Google identity provider (no
  Keycloak login form; set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, redirect URI
  `http://localhost:11095/realms/wattprint/broker/google/endpoint`). A new Google user gets the role `user`; give `admin` in the
  Keycloak console (http://localhost:11095, realm `wattprint`, Users > Role mapping). The seeded `admin` user has a password but
  no way to use it through the apps; the Keycloak console itself lives in the `master` realm.
- Realm `wattprint`: public client `wattprint-mobile` (authorization code + PKCE, redirect `wattprint://auth`, no direct
  grants), resource client `wattprint-api` (bearer only; its audience is added to access tokens by a mapper), realm roles
  `admin` and `user`, self-registration off, brute-force protection on.
- First start imports `keycloak/realm/wattprint-realm.json` (later starts skip it: edit realms in the console, or
  `docker compose rm -sfv keycloak keycloak-db` and delete the `wattprint_keycloak_pg18data` volume to re-import). It creates
  the user `admin` (email `admin@wattprint.local`, roles `admin`+`user`) with the password from `WATTPRINT_ADMIN_PASSWORD`
  (at least 12 characters, the realm's password policy).
- Sessions: access token 15 min; the refresh token lives as long as the Keycloak SSO session (idle 30 days, max 90 days;
  Keycloak's default is 30 min idle, which would sign the mobile app out after half an hour unused). Refresh-token rotation
  is on (`revokeRefreshToken=true`, `refreshTokenMaxReuse=0`, RFC 9700): see `docs/keycloak-auth.md`. Login and admin events are kept 7 days.
- The app signs users in with Keycloak and sends `Authorization: Bearer <access_token>`. The API verifies it locally with the
  realm's JWKS (RS256; `iss`, `aud=wattprint-api`, `azp=wattprint-mobile`, `exp`). No Keycloak call per request.
- `tb_users` is a local profile with a UUIDv7 `id` (`uuidv7()` server default, `uuid.uuid7` in the ORM); the first valid request stores the token's external `sub` in
  `keycloak_sub`. Business tables use the local UUID for foreign keys. A v7 id reveals its creation time (`uuid_extract_timestamp`), so ids are not secrets. A user whose email already exists under
  another account gets 409. Roles come from `realm_access.roles`.
- `GET /api/v1/users/me` returns the profile and roles; `GET /api/v1/users` needs the `admin` role (403 otherwise).
- Issuer: `KEYCLOAK_ISSUER` must equal the URL clients use (`KEYCLOAK_PUBLIC_URL`); the API itself reaches Keycloak as
  `http://keycloak:11095` (`KEYCLOAK_JWKS_URL`). A phone with `adb reverse tcp:11095 tcp:11095` uses `localhost`. On a LAN phone set
  `KEYCLOAK_BIND=0.0.0.0` and both URLs to the LAN IP.
- `start-dev` is for development only (HTTP, relaxed checks). Production: `start`, TLS, a real hostname, a secret admin password.

Swagger (`/docs`) cannot obtain tokens (the Keycloak client is mobile-only); call the API with an access token taken from a
login through the app.

### Hardening before production

Known deviations from Keycloak/OAuth best practice, kept on purpose for development:

- Refresh-token rotation is on. Both clients refresh single-flight (web: in-process only, so several web instances
  need a shared lock or sticky sessions; Expo: one in-flight refresh plus an in-memory `unsaved` token).
- Web sign-out is RP-initiated (redirect with `id_token_hint` + `post_logout_redirect_uri`). Expo ends the server
  session with a back-channel `POST .../logout` (a browser hop adds nothing there).
- `start-dev`, HTTP and `sslRequired=external`: production needs `start`, TLS, a real hostname, `sslRequired=all`, https
  redirect URIs and secrets from a secret store.
- The mobile redirect is the custom scheme `wattprint://auth` (shared by the dev/preview/production builds); PKCE protects the
  code, Android App Links would be stricter.
- Access tokens stay valid until `exp` (15 min) after logout; the API does not check revocation.

## Adding a router

1. Create `app/routers/x.py` with an `APIRouter(prefix="/x", tags=["x"])`.
2. Import it in `app/main.py` and add it to the tuple in the `for module in (health, users):` loop,
   which mounts every router under `/api/v1`.

## Migrations and tests

Revisions are hand-written (not autogenerate), because hypertables, continuous aggregates, grants and
cross-schema views need explicit DDL. Put new public business objects in `versions/public/`, new AI
objects in `versions/ai/`, and changes to existing objects or the shared linear migration flow in
`versions/updates/`. All three locations feed the same Alembic revision chain.

```bash
docker compose exec api alembic revision -m "initial module" --version-path alembic/versions/public
# Use --version-path alembic/versions/ai for AI schema revisions.
# Use --version-path alembic/versions/updates for changes to existing objects or shared flow.
docker compose exec api alembic upgrade head
docker compose exec api pytest
docker compose exec api ruff check app tests alembic
```

Tests run inside the `api` container (database access). Token tests sign with a throwaway RSA key and stub the JWKS lookup, so Keycloak is not needed.

## TODO

- Apple as an additional Keycloak identity provider (Google is already configured)
- SMTP in Keycloak (email verification, password reset)
- AI query execution and validation over `ai.fact_energy`
- CI
