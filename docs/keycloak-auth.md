# Keycloak auth (wattprint)

## Architecture
- Keycloak 26.2 runs in `docker-compose.yml` (`keycloak` + `keycloak-db`), realm `wattprint` imported from
  `keycloak/realm/wattprint-realm.json`. Dev port 11095 (`KEYCLOAK_PORT`).
- Clients: `wattprint-mobile` (public, PKCE S256, redirect `wattprint://auth`), `wattprint-web` (confidential, redirect
  `http://localhost:11092|3000/auth/callback`), `wattprint-api` (bearer-only; audience mapper puts it in `aud`).
- Sign-in is Google only: IdP `google`, flow `browser-google` redirects straight to it, `kc_idp_hint=google`.
- FastAPI is a resource server: verifies RS256 JWT via JWKS (`iss`, `aud`, `exp`, `sub`, `typ=Bearer`, `azp` in
  `KEYCLOAK_CLIENT_IDS`), creates the `users` row on first request (`id` = `sub`), roles from `realm_access.roles`.
  JWKS down -> 503, bad token -> 401, inactive user -> 403, email under another id -> 409.
- Future AI service: another resource server with its own audience; it verifies the same JWKS.

## Decisions
- Refresh-token rotation ON (`revokeRefreshToken=true`, `refreshTokenMaxReuse=0`); clients serialize refreshes.
- Web logout: RP-initiated. Expo logout: back-channel POST (server session is ended either way).
- Custom scheme redirect for mobile is acceptable with PKCE; App Links would be stricter.

## Run
- `docker compose up -d`; phone: `adb reverse tcp:11094 tcp:11094`, `tcp:11093`, `tcp:11095`.
- Env: see `.env.example` (admin password >= 12 chars, `WATTPRINT_WEB_CLIENT_SECRET`, `GOOGLE_CLIENT_ID/SECRET`).
- Re-import the realm: `docker compose rm -sfv keycloak keycloak-db`, `docker volume rm wattprint_wattprint_keycloak_pgdata`,
  `docker compose up -d`. New realm = new user `sub`: delete stale `users` rows or they answer 409.
- Google consent screen is in Testing mode: only listed test users can sign in.

## Verified
- API: 319 tests. Expo: `pnpm check` 501 tests. Web: `pnpm check` 15/15, `pnpm build`.
- Web in Chrome with real Google login: parallel `/dashboard` requests after the access token expired (90 s test
  value) all 200, no `REFRESH_TOKEN_ERROR`; sign-out returns to `/sign-in`. Lifespan restored to 900.
- Phone (Pixel 8a): Google sign-in, sign-out, cold start; Settings > profile card reads GET /users/me from FastAPI, also after the 60 s test token expired (200, no 401 reached the API). Web: Bearer call to `/users/me` after the 60 s test token expired, 4 parallel requests all 200.

## Open items
- Production: domain, HTTPS, `start` mode, `sslRequired=all`, secrets store.
- Access token stays valid until `exp` after logout (no revocation check).
- Web calls FastAPI only from the Overview page (`features/profile`, GET /users/me); no other data path yet.
