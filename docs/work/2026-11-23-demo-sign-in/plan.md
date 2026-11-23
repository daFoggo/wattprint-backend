# Demo sign-in by REFIT home: implementation plan
Spec: docs/work/2026-11-23-demo-sign-in/spec.md (approved). Status: approved. Record: none
Build: inline (sdlc `build` role). Base: backend `7baf2d0`, web `3a1ec5e` (both trees already dirty with the
sdlc-init setup; the review package diffs from these commits).

**Goal:** a visitor picks a seeded REFIT home in a dialog on the sign-in page and lands on its dashboard.
**Architecture:** backend password grant (client `wattprint-web`) behind two public endpoints; the dashboard's
server action stores the returned tokens through `@workspace/auth` exactly like the OAuth callback.
**Stack:** FastAPI + httpx + tomllib; Next.js 16 server actions, vitest, Hairline UI.

## Global constraints
- Client for the grant: `wattprint-web`; scope `openid profile email roles`; httpx timeout 10 s.
- Answer of `/demo/homes` holds no email, password, user or home id.
- Vendored Hairline files only through `packages/ui/hairline/patch.mjs` + `pnpm --filter @workspace/ui hairline`.
- No secret printed or written to a tracked file. Only `wp2-api` is recreated; nothing of `detectricity` touched.
- Copy in `apps/dashboard/messages/{vi,en}/auth.json` under `demo`.

## Review focus
1. Keycloak rejects the grant (password changed, account disabled) → 503, Keycloak body not leaked (Task 1 test).
2. A `house` that is in the toml but not seeded (5) → 404, not a Keycloak call (Task 1 test).
3. Tokens from the backend that fail verification (wrong `azp`, expired) → `signInWithTokens` throws, no cookie
   written (Task 3 test).
4. Backend down when the sign-in page renders → page renders without the demo button (Task 4: `getDemoHomes`
   catches → `[]`).
5. Double click / clicking a second card while the first runs → cards disabled while pending (Task 5, checked in
   the running app).

---

### Task 1: backend `demo` endpoints
Standards: `.claude/rules/auth.md`, `.claude/rules/tests.md`.

**Files:** create `app/modules/auth/services/demo.py`, `app/modules/auth/routes/demo.py`,
`app/modules/auth/schemas/schema_demo.py`, `tests/test_demo_api.py`; modify `app/config.py`,
`app/modules/auth/{routes,schemas,services}/__init__.py`, `app/modules/auth/utils/exceptions.py`,
`tests/test_api.py` (`PUBLIC`).

**Interfaces (produces):**
- `GET /api/v1/demo/homes -> list[DemoHome]`, `DemoHome{key: str, house: int, name: str, devices: list[DemoDevice{label, name}]}`
- `POST /api/v1/demo/session` body `DemoSessionIn{house: str (1..32)}` → `DemoTokens{access_token, refresh_token, id_token, expires_in: int, refresh_expires_in: int}`
- `services.demo.demo_homes(db) -> list[DemoHome]`; `services.demo.demo_session(db, key) -> DemoTokens`;
  module-level `_transport: httpx.AsyncBaseTransport | None = None` for tests.
- Settings: `demo_password`, `wattprint_web_client_secret`, `demo_homes_file`, property `token_url`.

- [ ] Step 1: write `tests/test_demo_api.py` (fixtures: a tmp toml with houses 2 and 5 via `monkeypatch.setattr(settings, "demo_homes_file", ...)`, owner of 2 inserted as user + `tb_home_member`, 5 not; Keycloak via `httpx.MockTransport` set on `_transport`):
  - `test_homes_lists_only_seeded` → `[{"key": "2", "house": 2, "name": "REFIT House 2", "devices": [...no "Other"]}]`, no `"@"` in the body.
  - `test_session_posts_password_grant_for_owner` → form has `grant_type=password`, `client_id=wattprint-web`, `username=<owner email>`, `scope=openid profile email roles`; answer equals the five token fields.
  - `test_session_unknown_or_unseeded_404` (`"9"` and `"5"`), MockTransport never called.
  - `test_session_keycloak_rejects_503` (401 `invalid_grant`) → 503, body has no `invalid_grant`.
  - `test_session_unconfigured_503` (`demo_password=""`).
- [ ] Step 2: run `docker compose exec -T api pytest -q tests/test_demo_api.py` → fails (404 route).
- [ ] Step 3: implement; add `("GET", "/api/v1/demo/homes")`, `("POST", "/api/v1/demo/session")` to `PUBLIC` (the
      public test sends GET to POST paths too: check how it handles non-GET and match).
- [ ] Step 4: rerun → pass; `uv run ruff format` the touched files.

### Task 2: config, realm, compose, docs; apply to wp2 (approved)
Standards: `.claude/rules/auth.md`.

**Files:** `docker-compose.yml` (api env `DEMO_PASSWORD: ${DEMO_PASSWORD:-}`, `WATTPRINT_WEB_CLIENT_SECRET: ${WATTPRINT_WEB_CLIENT_SECRET:-}`),
`keycloak/realm/wattprint-realm.json` (`wattprint-web.directAccessGrantsEnabled: true`), `.claude/rules/auth.md`
and `docs/keycloak-auth.md` (the two public demo endpoints, Direct Access Grants on `wattprint-web` and why).

- [ ] Step 1: edit the three files.
- [ ] Step 2: admin REST (token from `master` with the admin password read from `.env` in the same shell, never
      echoed): GET client `wattprint-web`, set `directAccessGrantsEnabled=true`, PUT it back on `http://localhost:13095`.
- [ ] Step 3: `docker compose up -d api`; then `curl -s localhost:13093/api/v1/demo/homes` → House 2 only, and
      `POST /demo/session {"house":"2"}` → 200 with the five fields (print only the keys).

### Task 3: `@workspace/auth` `signInWithTokens`
Standards: web `.claude/rules/auth.md`.

**Files:** `packages/auth/src/types.ts`, `packages/auth/src/keycloak/server.ts`,
`packages/auth/src/__tests__/keycloak-provider.test.ts`.

**Interfaces (produces):** `AuthProvider.signInWithTokens(tokens: KeycloakTokenResponse): Promise<void>` (type
re-exported from `types.ts` as `TokenSet`); internal `storeTokens(cookieStore, tokens)` used by `exchangeCode`,
`refreshSession` and `signInWithTokens`.

- [ ] Step 1: tests: `signInWithTokens stores the three cookies when the token verifies` (spy `verifyKeycloakJwt`
      → claims; jar has `.access`, `.refresh`, `.id`); `signInWithTokens throws and stores nothing when the token
      does not verify` (spy → `null`).
- [ ] Step 2: `pnpm --filter @workspace/auth test` → the two fail.
- [ ] Step 3: implement; Step 4: rerun → pass.

### Task 4: dashboard server side
Standards: web `.claude/rules/{auth,dashboard-data,routes}.md`.

**Files:** create `apps/dashboard/features/auth/server.ts`; modify `apps/dashboard/features/auth/actions.ts`.

**Interfaces (produces):** `type DemoHome` (same shape as the backend), `getDemoHomes(): Promise<DemoHome[]>`
(any error → `[]`), `signInAsDemoHomeAction(house: string): Promise<{ error: string } | void>` (zod
`z.string().min(1).max(32)`; on success `updateTag(SESSION_TAG)` and `redirect` to the dashboard in the current
locale; on failure `{ error: t("demo.failed") }`).

- [ ] Step 1: implement (no unit test: thin glue over `apiFetch` and Task 3, exercised in the running app in Task 5).

### Task 5: dialog, cards and house drawing
Standards: web `.claude/rules/{ui,vendored-ui,i18n}.md`, `docs/design-system.md`, skill `hairline-ui`.

**Files:** `packages/ui/hairline/patch.mjs` (export `box`, `line` in `empty-state-scenes.ts`; export `FILL`,
`STROKE` in `empty-state.tsx`), `packages/ui/package.json` (export `./components/hairline/empty-state-scenes`),
create `apps/dashboard/features/auth/components/demo-homes-dialog.tsx`, `demo-house-scene.tsx`; modify
`apps/dashboard/app/[locale]/(auth)/sign-in/page.tsx`, `apps/dashboard/messages/{vi,en}/auth.json`.

**Interfaces:** `<DemoHomesDialog homes={DemoHome[]} action={signInAsDemoHomeAction} />`; `<DemoHouseScene devices={DemoDevice[]} />`.

- [ ] Step 1: patches + `pnpm --filter @workspace/ui hairline` (expect only the four exports to change).
- [ ] Step 2: scene: TILE, a house (box walls + gable roof from two quads + a door/window face), one object per
      device label in front (Fridge tall box, WashMach/Dishwash cubes with a round door `line`, Microwave, Toaster,
      Kettle small boxes; unknown label → small box), at most 6, fixed positions; `role="img"` + `aria-label`.
- [ ] Step 3: dialog: trigger `Button variant="outline"`, Hairline `Dialog`, cards as `<button>`s (grid `sm:grid-cols-2`
      only when > 1 home), `useTransition` for pending, `FormError` on `{error}`.
- [ ] Step 4: sign-in page: `<Suspense>` around an async component that renders the dialog when `homes.length > 0`.
- [ ] Step 5: `pnpm check`; open `http://localhost:11092/sign-in` (vi and `/en`), open the dialog, sign in as
      House 2, land on the dashboard, sign out; light and dark; mobile width.

### Task 6: review and done
- [ ] R1 (opus, full) on both repos' packages → one fix pass → R2/R3 scoped as needed.
- [ ] `docker compose exec -T api pytest -q` (full) and `pnpm check` green; debt to `wattprint-nextjs/docs/debt.md`;
      trial notes `[T03]` in `../sdlc-trial-notes.md`.

### Task 7: debt fixes after R2 (dashboard-only sessions, caps, lockout unlock)
**Files:** backend `app/config.py` (`demo_admin_client_secret`), `app/modules/auth/services/demo.py` (`_quota`,
`_unlock`, secret check), `routes/demo.py` (headers `X-Demo-Secret`, `X-Demo-Visitor`), `utils/exceptions.py`
(`DemoForbiddenError` 403), `keycloak/realm/wattprint-realm.json` (client `wattprint-demo-admin` + its service-account
roles), `docker-compose.yml`, `.env.example`, `docs/keycloak-auth.md`; web `apps/dashboard/features/auth/server.ts`.
**Standards:** `.claude/rules/auth.md` (both repos), `data.md` (`shortcut:` for the per-process counter).
- [x] Tests first: `test_session_needs_the_dashboard_secret_403`, `..._rate_limited_per_visitor_429`,
      `..._rate_limited_globally_429`, `..._clears_a_lockout_and_retries`, `..._without_admin_client_does_not_unlock_503`,
      `..._unlock_failure_503`; web `features/auth/__tests__/demo-server.test.ts` (failed on the old `server.ts`).
- [x] Live: client created through the admin REST API on `wp2-keycloak`, secret in `.env`, `wp2-api` recreated;
      e2e: owner locked by 11 wrong passwords, `/demo/session` without the secret 403, through the dashboard 200.
- [x] R3 scoped on both repos: one Should fix (empty visitor aliasing the global window), fixed with a failing test first.
