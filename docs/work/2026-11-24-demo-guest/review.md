# Review: demo guest accounts

Bases: backend b7484eecc85f6efeab76d25ce8bc8dbda5cf0ca7, web 13bdb6559d93f75bdc25cf1de07594a97dac9d4c (snapshots).
R1 package snapshots: backend 7e94794f038341c925ce877b92d84828b1e79eb4, web fe5e9c593607656441d73a2f31384da87c867a30.

## R1 (full, opus): fix 1, 2
- Must 1: features/auth/server.ts read the client secret (rule: only the DAL and lib/env read secrets) → fixed:
  `demoGuestSecret()` in lib/dal.ts; ESLint `featureRestrictions` now bans `@/lib/env` and
  `@workspace/auth/config` in features/ (failed on server.ts first).
- Must 2: per-process demo guest rate windows missing from the debt list → added.
- Minor 3 (JWT errors answer 500), 4 (silent purge failure) → web docs/debt.md. Minor 5 (REVIEW.md tokenless list)
  fixed: a stale policy would flag the endpoint as Must fix.
- Declined to judge (product calls, accepted per spec): cap exhaustion by a few IPs in ~25–100 min; Wappi cost per
  guest; a purged guest's still-valid token re-creates a row (purged a day later).
- Reviewer's not-checked items, verified: live Keycloak updated (client credentials 200, live endpoint returned
  tokens, dev click signed in as "Khách demo"); per-visitor cap behind apps/web rewrite — dashboard is served
  directly by nginx at wattprint.ptitai.org, not through the landing rewrite.

## R2 (scoped, sonnet): ship
- Must 1 and 2 addressed; no new breakage. pnpm check 17/17 (the features ban leaves `@/lib/env.public` alone);
  backend pytest 576 passed, 1 skipped (torch-only).

## Debt payoff (lane M, spec debt-spec.md) R1 (sonnet): ship
- Minor 1 (home name truncated; ui.md: reflow) fixed. Minor 2 (px/py on a native button) — Ruling: not a breach,
  the rule covers Hairline/shadcn components — none.
