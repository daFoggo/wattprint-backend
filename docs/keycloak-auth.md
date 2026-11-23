# Keycloak auth (wattprint)

## Architecture
- Keycloak 26.2 runs in `docker-compose.yml` (`keycloak` + `keycloak-db`), realm `wattprint` imported from
  `keycloak/realm/wattprint-realm.json`. Dev port 11095 (`KEYCLOAK_PORT`).
- Clients: `wattprint-mobile` (public, PKCE S256, redirect `wattprint://auth`), `wattprint-web` (confidential, redirect
  `http://localhost:11092|3000/auth/callback`), `wattprint-api` (bearer-only; audience mapper puts it in `aud`).
- Sign-in: Keycloak's standard `browser` flow. Its login page (email + password, a Google button) uses the
  `wattprint` login theme, built in `wattprint-web/apps/keycloak-theme` (Keycloakify, React) and mounted from
  `keycloak/providers/` (jar not committed: `pnpm --filter keycloak-theme build:jar` there, then restart Keycloak).
  Clients that pass `kc_idp_hint=google` skip the page. Languages: `vi` (default) and `en`, picked by `ui_locales`.
  Sign-up (email as username), email verification and password reset are on; Keycloak mails through `SMTP_*`
  (dev default: the `mailpit` service, inbox http://localhost:11099; emails use the theme's Vietnamese texts).
  New users get `user` through `default-roles-wattprint`.
- FastAPI is a resource server: verifies RS256 JWT via JWKS (`iss`, `aud`, `exp`, `sub`, `typ=Bearer`, `azp` in
  `KEYCLOAK_CLIENT_IDS`), creates the `tb_users` row on first request with a local UUIDv7 `id` and stores `sub` in
  `keycloak_sub`; roles come from `realm_access.roles`.
  JWKS down -> 503, bad token -> 401, inactive user -> 403, email under another id -> 409.
- Demo sign-in: public `GET /api/v1/demo/homes` (the seeded homes of `scripts/demo_homes.toml`, no emails) and
  `POST /api/v1/demo/session {house}`: the API does a password grant through `wattprint-web` as that home's owner
  with `DEMO_PASSWORD` and returns Keycloak's tokens; the dashboard stores them like the OAuth callback. This is why
  `wattprint-web` has Direct Access Grants on (anyone holding its secret, which stays server-side, can password-grant
  any user). Demo system: anyone may sign in as a demo owner, on purpose. Only the dashboard may ask (header
  `X-Demo-Secret` = the web client's secret, else 403); it passes the visitor's address in `X-Demo-Visitor`, capped
  at 5 sessions a minute per visitor and 20 overall (429). A wrong password typed for the shared owner on the
  Keycloak page locks it for everyone, so on a refused grant the API clears that owner's lockout once with the
  service account `wattprint-demo-admin` (`DEMO_ADMIN_CLIENT_SECRET`; realm-management `manage-users`,
  `view-users`) and retries. That secret can edit every realm user: keep it in the API env only.
- Future AI service: another resource server with its own audience; it verifies the same JWKS.

## Decisions
- Google sign-in for an email that already has a password account links only after re-authentication
  (flow `first broker login (re-auth)`, email-link verification disabled): otherwise someone could pre-register a
  victim's address, wait for the victim to link Google, and keep a working password on the account. The victim uses
  "Forgot password" instead, which replaces that password.
- Password policy: 12+ characters, an uppercase, a lowercase, a digit, a special character, not the email
  (`passwordPolicy`). The theme's sign-up checklist and meter read these rules from Keycloak, so change them
  only in the realm.
- Brute force: lockout after 10 failures, waits from 1 to 15 minutes (`failureFactor`, `waitIncrementSeconds`,
  `maxFailureWaitSeconds`).
- Never set `KEYCLOAKIFY_SPA_DEV_SERVER_PORT` outside local theme development: the theme would load its scripts from
  `localhost` on the visitor's machine.
- Refresh-token rotation ON (`revokeRefreshToken=true`, `refreshTokenMaxReuse=0`); clients serialize refreshes.
- Web logout: RP-initiated. Expo logout: back-channel POST (server session is ended either way).
- Custom scheme redirect for mobile is acceptable with PKCE; App Links would be stricter.

## Run
- `docker compose up -d`; phone: `adb reverse tcp:11094 tcp:11094`, `tcp:11093`, `tcp:11095`.
- Env: see `.env.example` (admin password >= 12 chars, `WATTPRINT_WEB_CLIENT_SECRET`, `GOOGLE_CLIENT_ID/SECRET`).
- Re-import the realm: `docker compose rm -sfv keycloak keycloak-db`, `docker volume rm wattprint_wattprint_keycloak_pg18data`,
  `docker compose up -d`. New realm = new user `sub`: delete stale `tb_users` rows or they answer 409.
- Google consent screen is in Testing mode: only listed test users can sign in.

## Verified
- API: 319 tests. Expo: `pnpm check` 501 tests. Web: `pnpm check` 15/15, `pnpm build`.
- Web in Chrome with real Google login: parallel `/dashboard` requests after the access token expired (90 s test
  value) all 200, no `REFRESH_TOKEN_ERROR`; sign-out returns to `/sign-in`. Lifespan restored to 900.
- Phone (Pixel 8a): Google sign-in, sign-out, cold start; Settings > profile card reads GET /users/me from FastAPI, also after the 60 s test token expired (200, no 401 reached the API). Web: Bearer call to `/users/me` after the 60 s test token expired, 4 parallel requests all 200.

## Open items
- Before production: rate-limit `/login-actions/registration` and `/login-actions/reset-credentials` at the reverse
  proxy and add a captcha (reCAPTCHA/Turnstile keys) to registration; set real `SMTP_*` (SPF/DKIM on the sender).
- `default-roles-wattprint` keeps Keycloak's `offline_access` (offline tokens); drop it if no client needs them.
- Production: domain, HTTPS, `start` mode, `sslRequired=all`, secrets store.
- Access token stays valid until `exp` after logout (no revocation check).
- Web calls FastAPI only from the Overview page (`features/profile`, GET /users/me); no other data path yet.
