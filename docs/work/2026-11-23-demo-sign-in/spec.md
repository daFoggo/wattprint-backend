# Spec: Demo sign-in by REFIT home
Intent: docs/work/2026-11-23-demo-sign-in/intent.md. Status: approved. Record: none

Covers both repos (wattprint-backend and wattprint-nextjs); the artifacts live here only.

## Requirements

Backend
1. `GET /api/v1/demo/homes`, no token. Answers the homes of `scripts/demo_homes.toml` (in file order) **whose owner
   account is a member of a home in the database** (seeded), each
   `{ "key": str, "house": int, "name": str, "devices": [{ "label": str, "name": str }] }`:
   `key` = toml `key` or `str(house)`, `name` = toml `name` or `"REFIT House <n>"`, `devices` = the toml `devices`
   map minus `Other`, `label` = NILM label (`Fridge`, `WashMach`, ...), `name` = REFIT name. Unseeded homes (5,
   5-heat today) are left out. No email, password or id in the answer.
2. `POST /api/v1/demo/session`, no token, body `{ "house": str }` (a `key` from 1). Does a Keycloak password
   grant at the realm token endpoint as that home's **owner**: `grant_type=password`, `client_id=wattprint-web`,
   its client secret, `username=<owner email>`, `password=DEMO_PASSWORD`, `scope=openid profile email roles`.
   Answers `{ access_token, refresh_token, id_token, expires_in, refresh_expires_in }` copied from Keycloak.
3. Errors (RFC 7807 like the rest of the API): unknown or unseeded `house` 404; `DEMO_PASSWORD` or the web client
   secret not configured 503; Keycloak unreachable or rejecting the grant 503 (message: demo sign-in unavailable).
   Keycloak's error body is logged, never returned.
4. Config (`app/config.py`): `demo_password` (env `DEMO_PASSWORD`), `wattprint_web_client_secret` (env
   `WATTPRINT_WEB_CLIENT_SECRET`, the same `.env` line the realm import uses), `demo_homes_file`
   (default `scripts/demo_homes.toml`). Token endpoint = the JWKS URL with `/certs` replaced by `/token`, so in
   compose it goes to `http://keycloak:11095` like the JWKS fetch.
5. Compose `api` gets `DEMO_PASSWORD` and `WATTPRINT_WEB_CLIENT_SECRET` from `.env`.
6. Realm `wattprint-realm.json`: client `wattprint-web` gets `directAccessGrantsEnabled: true`.
7. `tests/test_api.py` `PUBLIC` lists both endpoints; the auth rule card and `docs/keycloak-auth.md` name them.

Web (dashboard)
8. `@workspace/auth` `AuthProvider` gets `signInWithTokens(tokens)`: verifies the access token exactly as
   `getSession` does (JWKS, issuer, `azp` = this client) and throws if it fails; then stores access, refresh and id
   cookies exactly as `oauth.exchangeCode` does (one shared helper, so the two cannot drift).
9. Sign-in page: under the Google and email buttons, a button "Vào nhà demo" / "Try a demo home" opens a Hairline
   `Dialog`. Rendered only when `GET /demo/homes` answers at least one home; if the backend is down the page is
   unchanged.
10. The dialog lists one card per home: an isometric drawing (tile + house + one small object per device label,
    built with the EmptyState scene helpers, theme colours, no animation), the home name and the device names.
    One home: one full-width card. Two or more: two columns from `sm`.
11. Clicking a card runs a server action: validates `house` (non-empty string, max 32 chars), calls
    `POST /demo/session`, `signInWithTokens`, then redirects to the dashboard in the current locale. While it runs
    the clicked card shows pending and all cards are disabled; on failure the dialog shows the existing
    `FormError` with a translated message and the cards are enabled again.
12. All copy in `messages/{vi,en}` under `auth.demo`.

## Design

Backend, inside the auth module (riskyPath `app/modules/auth/**`, rule card `.claude/rules/auth.md`):
- `app/modules/auth/services/demo.py`: `demo_homes(db)` reads the toml with `tomllib` and keeps the homes whose owner
  email appears in `tb_users` joined to `tb_home_member` (`User` from auth, `HomeMember` via `app.modules.home.api`);
  `demo_session(db, key)` finds the home, posts the grant with `httpx.AsyncClient` (already a dependency, timeout 10 s).
- `app/modules/auth/routes/demo.py`: router `prefix="/demo", tags=["demo"]`, included in `routes/__init__.py`.
- Schemas in `schemas/schema_demo.py`; errors as `AppError` subclasses in `utils/exceptions.py` (existing pattern).
- Tests `tests/test_demo_api.py`: Keycloak replaced with `httpx.MockTransport` through monkeypatch; checks the
  filter, the posted form, the pass-through, 404 and the 503 cases.

Web:
- `packages/auth/src/keycloak/server.ts`: extract `storeTokens(cookieStore, tokens)` from `exchangeCode`, reuse it
  in `refreshSession`, `exchangeCode` and the new `signInWithTokens`. Test in `keycloak-provider.test.ts`.
- `apps/dashboard/features/auth/server.ts`: `getDemoHomes()` (via `apiFetch`, any error → `[]`) and
  `createDemoSession(house)`.
- `apps/dashboard/features/auth/actions.ts`: `signInAsDemoHomeAction(house)` returns `{ error }` on failure,
  redirects on success.
- `features/auth/components/demo-homes-dialog.tsx` (client) and `demo-house-scene.tsx` (client).
- Drawing helpers: `packages/ui/hairline/patch.mjs` gets two patches: export `box` and `line` from
  `empty-state-scenes.ts`, and export the `FILL`/`STROKE` token maps from `empty-state.tsx`; `packages/ui/package.json`
  exports `./components/hairline/empty-state-scenes`. Then `pnpm --filter @workspace/ui hairline`.
- Follows `.claude/rules/{auth,ui,vendored-ui,i18n}.md`, `docs/design-system.md`, the `hairline-ui` skill.

Applying to the running wp2 stack (needs the user's go, see below): enable Direct Access Grants on
`wattprint-web` through the Keycloak admin REST API (no realm re-import, so no new `sub`s), and recreate only the
`api` container (`docker compose up -d api`) so it gets the two env vars.

## Approaches considered
- **A, chosen by the user:** backend password grant with `DEMO_PASSWORD`. The password and the grant stay in the
  backend; the web only receives tokens. Cost: the backend holds the web client's secret.
- B: the web does the password grant itself. No backend change, but the demo password moves into the web env.
- C: Keycloak token exchange / impersonation by a service account. No shared password, but a preview feature and a
  much larger realm change for a demo.
- Client for the grant: `wattprint-web`, because the dashboard verifies `azp` = its own client and refreshes with
  its secret; a token from another client (e.g. a new `wattprint-demo` or the public `wattprint-mobile`) would be
  rejected by the dashboard and could not be refreshed.

## Areas of concern
- The auth card says every endpoint needs a token except health and provinces. This adds two public endpoints, one
  of which hands out real tokens for the demo owners: intended (demo system, no limits on demo users). The card,
  the doc and the `PUBLIC` test are updated so the exception is explicit.
- Direct Access Grants on `wattprint-web` lets anyone holding its client secret password-grant any realm user. The
  secret stays server-side (backend and dashboard env only). Realm brute-force protection still applies.
- The realm card says realm changes apply only on re-import (which issues new `sub`s). The live change goes through
  the admin API instead; the JSON is edited so a future import matches.
- Hairline MCP is not available in this session and the `hallmark` skill is not installed: the UI follows the
  repo's `hairline-ui` skill and design docs instead.

- Debt fixes after R2 (2026-11-23): (1) each grant is a real Keycloak session, so `/demo/session` now answers
  only the dashboard (its client secret in `X-Demo-Secret`, constant-time compare) with a cap per visitor
  (`X-Demo-Visitor`, the address nginx saw) and a global backstop. The visitor header is only as honest as the
  path to `next start`: reachable directly, a client can rotate it, and only the global cap holds. Caps are counted
  per API process. (2) A shared owner is locked by anyone typing wrong passwords for it; the API clears the lockout
  with a service account holding realm-management `manage-users` (realm-wide user power if its secret leaks) and
  retries once. This defeats the lockout for demo owners only, whose password is already handed out by design.

## Open questions carried forward
- None: the user approved the live Keycloak change and recreating `wp2-api` (2026-11-23).
