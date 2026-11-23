# Intent: Demo sign-in by REFIT home
Author: dung. Status: accepted.
Source: conversation 2026-11-23 (task T03). Record: none

## Problem
A visitor of the demo cannot see a home's dashboard without knowing a demo account's email and the shared
password. The demo accounts already exist (one owner per home, created by `scripts/seed_demo_homes.py` from
`scripts/demo_homes.toml`, password `DEMO_PASSWORD`), but the sign-in page only offers Keycloak's login page.

## Proposed outcome
On the dashboard sign-in page a button opens a dialog listing the demo homes as cards, each with an isometric
drawing of the house and its appliances. Clicking a card signs the visitor in as that home's owner and lands on the
dashboard, with a session identical to one made by the OAuth callback (same cookies, refresh, sign-out).

## Affected users and systems
- Visitors of the demo (anonymous).
- wattprint-backend: new public `GET /demo/homes`, `POST /demo/session`; compose env of `api`.
- Keycloak realm `wattprint`: Direct Access Grants on one client.
- wattprint-nextjs: sign-in page, a server action, `@workspace/auth` (store tokens), vendored Hairline patch.

## Constraints
- Approach A is decided: the backend does the password grant with `DEMO_PASSWORD` and returns the tokens.
- Demo system: demo users get no extra permission limits.
- Today only House 2 is seeded (House 5 has no CSV, 3 and 6 no model): the UI must be right with a single home.
- Vendored Hairline files change only through `packages/ui/hairline/patch.mjs`.
- Shared server: no container stop/rebuild without asking, never touch the `detectricity` stack, no secrets printed.

## Open questions
- Applying the realm change and the new `api` env to the running wp2 stack: the user approves (see spec).
