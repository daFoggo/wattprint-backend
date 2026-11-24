# Plan

1. Realm: `wattprint-demo-admin` client (service account, realm-management manage-users + view-users, secret
   `${DEMO_ADMIN_CLIENT_SECRET}`); `wattprint-web` directAccessGrantsEnabled true. Live: kcadm. Test: realm JSON
   test (if any) + a live token grant.  Standards: .claude/rules/auth.md
2. Backend config `wattprint_web_client_secret`, `demo_admin_client_secret`, `token_url`; compose passes them.
3. `services/demo.py`: `create_guest` (+ `_quota`, `_admin`, `_purge`), exceptions, schema `DemoTokens`, route.
   Tests first: test_demo_api.py — secret refused, unknown key, cap, success path (Keycloak via MockTransport:
   user created, grant, viewer row), failure after create deletes the user, purge of an old guest.
   Standards: .claude/rules/auth.md, backend conventions.
4. Web: `packages/auth` `signInWithTokens` back (+2 tests); `features/auth` server `createDemoGuest`, action
   `startDemoAction` (+ tests), dialog wiring, messages; remove pick cookie, callback hook and their tests.
   Standards: .claude/rules/auth.md, dashboard-data.md, ui.md.
5. Verify: pytest, pnpm check, live click on dev and prod; docs (keycloak-auth.md, debt.md).
