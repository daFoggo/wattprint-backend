# Review: Demo sign-in by REFIT home (T03)

Lane L (auth is a riskyPath). Two repos.

| Repo | Base | R1 snapshot | R2 snapshot | R3 snapshot |
|---|---|---|---|---|
| wattprint-backend | 7baf2d0a21ebde1510bf72901f0753580923f595 | 24a7ed1 | 8155fa27617f3ccb0b4a04e28d1d2fba09915229 | 637ba11867c198cb1eb9d2f31d41b02296845d3e |
| wattprint-nextjs | 3a1ec5e2c633ea60c8355fc6920b23d492d51343 | 0bd804f | b7c28d8a9e3027588f32d516248b7e28a77676fe | 4d1e810287ebecc56bc8bf9f5aff071e68bea418 |

## R1 (opus, full)

No bug in the auth path itself. Findings:
1. Must fix: the SCENE patches in `packages/ui/hairline/patch.mjs` were not in the Hairline patch table
   (`docs/design-system.md`) or the hairline-ui skill. Fixed: row and skill entry added.
2. Should fix: no Vitest for `signInAsDemoHomeAction` / `getDemoHomes`. Fixed: `features/auth/__tests__/`.
3. Should fix: `<Suspense>` on the sign-in page had no fallback. Fixed: a sized skeleton.
4. Should fix: public `/demo/session` mints Keycloak sessions with no limit. Fixed in the R1 pass with a global
   cap (20 a minute); the per-visitor part went to debt, paid below.
5. Minor: the shared demo owner can be locked by brute-force protection. Went to debt, paid below.

## R2 (sonnet, scoped)

Verdict: ship. Findings 1-4 closed.

## Debt fixes after R2 (plan Task 7)

The user asked to pay the T03 debt (the global-only cap and the lockout). Not new scope: they finish findings 4 and 5.
- `/demo/session` answers only the dashboard (`X-Demo-Secret`, constant-time compare, else 403), caps each visitor
  (`X-Demo-Visitor`, 5 a minute) under the global 20.
- On a refused grant the API clears the owner's lockout with the `wattprint-demo-admin` service account and retries once.
- Live: client created on `wp2-keycloak` through the admin REST API; e2e verified (locked owner: right password
  401 at Keycloak, `/demo/session` 403 without the secret, 200 through the dashboard path).

## R3 (sonnet, scoped, last)

Findings 1 and 2 (global-only cap, lockout) ADDRESSED. New:
3. Should fix: an empty `X-Demo-Visitor` (no proxy headers) used the global window's key `""`, so unknown
   visitors shared 5 a minute and each success counted twice. Fixed after R3: the per-visitor window applies only
   to a known address; `test_session_unknown_visitor_only_hits_the_global_cap` failed first. Loop ends here (cap
   of three); this fix is not re-reviewed.
- Minor: `_unlock` reads `access_token` from a 200 without checking the body; a malformed answer becomes 500, not
  503. Sent to debt.
