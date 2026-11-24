# Spec: demo homes viewed read-only from the visitor's own account

Intent: intent.md. Status: approved (direction by the user, details delegated).

## Backend
1. `tb_home_member.role` allows `viewer` (migration on the check constraint). `HomeRead.role` gains `viewer`.
2. `GET /api/v1/demo/homes` unchanged (public).
3. `POST /api/v1/demo/homes/{key}/view` (signed in, `CurrentUser`; no membership needed): 404 unknown/unseeded key;
   409 `demo_not_for_members` when the account is owner/member of a home; otherwise makes the account a `viewer` of
   that home (insert, or move an existing viewer row: one home per account) and answers `HomeRead`.
4. `POST /api/v1/demo/session` is removed with the password grant, the per-process session caps, `_unlock`,
   `DemoTokens` and their errors and settings (`demo_admin_client_secret`; `wattprint_web_client_secret` and
   `demo_password` only if nothing else reads them).
5. Read-only viewers: a `WritableMembership` dependency answers 403 `home_read_only` for a viewer. It guards every
   write that changes the home's shared state: `PATCH /insights/alerts/{id}`, `POST /insights/alerts/{id}/feedback`,
   `POST /insights/watches`, `DELETE /insights/watches/{id}`, `POST /copilot/plans/{id}/accept` (and
   `PATCH /homes/current`, already owner-only). Per-account writes stay open: preferences, the viewer's own
   conversations, answer ratings, chat, voice.
6. Copilot: the tools `create_watch` and `propose_plan` answer an error the model reads ("this demo home is
   read-only") for a viewer, without writing.
7. Mail: alert mails and the other member mail skip viewers.
8. Realm file and compose: `wattprint-web` `directAccessGrantsEnabled: false`; client `wattprint-demo-admin` (and its
   service-account user) removed; `DEMO_ADMIN_CLIENT_SECRET` dropped from compose/.env.example; the api no longer
   gets `DEMO_PASSWORD` (the seed script still uses it to create the owners).
9. Running Keycloak (kcadm, no re-import): Direct Access Grants off on `wattprint-web`, `wattprint-demo-admin`
   deleted, every session of the demo owners logged out. Also the realm's default `admin-cli` (public, password grant
   on by Keycloak's default): turned off on the running realm and declared in the realm file, so "no client of this
   realm has a password grant" holds after a re-import too (the seed script uses the master realm's `admin-cli`).

## Web
10. `features/home` role enum gains `viewer`. A viewer sees a strip at the top of the dashboard: "Đang xem nhà demo
    <name> (chỉ xem) · Đổi nhà" ("Đổi nhà" opens the picker).
11. `NoHome` (account without a home) offers the demo homes picker (the sign-in dialog's cards); picking runs
    `viewDemoHomeAction(key)` → backend 3 → `updateTag` of the home data → the dashboard shows that home.
12. Sign-in page: the demo button opens the same cards as a preview with copy "Đăng nhập hoặc tạo tài khoản, rồi chọn
    một nhà để xem (chỉ xem)" and one button that starts the normal sign-in (Keycloak page: email, sign-up, Google).
13. Write controls are hidden for a viewer: home settings form (already owner-only), alert seen/feedback buttons,
    watch create/cancel, Wappi's plan accept button and watch widget cancel.
14. Removed: `signInAsDemoHomeAction`, `createDemoSession`, `@workspace/auth` `signInWithTokens` (only demo used it).

## Areas of concern
- The realm file also carries the mobile client's per-build redirect URIs (`wattprint-dev://auth`,
  `wattprint-preview://auth`): that is wattprint-expo docs/work/2026-11-23-scheme-per-env (requirement 3, reviewed
  there and applied with kcadm); it shares this file, so it ships in the same backend commit.
- Viewers of one demo home see each other's nothing (conversations are per account), but share the home's alerts
  list read-only. Acceptable for a demo.
- A real user with a home cannot view a demo home (one home per account). Accepted.
- Existing visitors lose their owner session at cutover and must sign in with their own account.
- The other session's uncommitted forecast/anomaly work touches copilot `tools.py`/insight: edit only the lines named
  here.
