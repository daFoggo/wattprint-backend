# Review instructions

Read by the sdlc reviewer before every review of this repo. Keep it under a page.

## What blocks a merge (Must fix)
- Behavior breaks, data leaks across homes or is lost, or a rule card in `.claude/rules/` is broken.
- Auth: an endpoint other than health, provinces and the demo sign-in pair (`/demo/homes`, `/demo/session`) reachable without a token, or reading another home's data.
- Data: an edited or reformatted applied migration, a write that bypasses `ingest_readings`, a change to
  `tb_reading` from NILM, a number computed by the LLM instead of a tool, personal data reaching storage or the LLM
  unmasked.
- Money or energy math (tariff tiers, coverage, rounding) changed without a test that pins the result.

## Should fix
- Risky logic without a test that fails when it breaks.
- A new table or view missing from the grant matrix in `tests/db/test_roles.py`.

## Do not report
- Anything ruff enforces (E, F, I, B, UP, N, formatting) or `scripts/check_boundaries.py` (module imports).
- Generated and vendored paths: `keycloak/providers/**`, `dataset/*.zip`, `dataset/training/*.zip`,
  `dataset/research_*/**` (research records), `docs/soa/**`, `uv.lock`.
- Deliberate scale limits marked `shortcut:` with their trigger.

## Cap
- At most five Minor findings; summarize the rest as a count.
