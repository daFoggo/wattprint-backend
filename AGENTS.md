# Repository instructions

FastAPI + TimescaleDB backend of WattPrint (NILM, billing, insight, copilot). This repo follows the sdlc process:
invoke the `sdlc` skill at the start of any code change (config: `.claude/sdlc.json`, review policy: `REVIEW.md`,
path-scoped rules: `.claude/rules/`).

## Commands

| What | Command | Healthy output |
|---|---|---|
| Verify (runs on every stop) | see `verify` in `.claude/sdlc.json`: ruff check + format check on `app tests alembic scripts`, `scripts/check_boundaries.py` | `All checks passed!`, `... files already formatted`, `module boundaries ok` |
| Tests (run before saying done; not in verify, too slow for the Stop hook) | `docker compose exec -T api pytest -q` (uses `<db>_test`, never the dev data); while iterating, pass the touched test files | `441 passed, 1 skipped` |
| Format a file you changed | `uv run ruff format <file>` | `1 file reformatted` or `left unchanged` |

`alembic/versions/**` is excluded from the formatter (`force-exclude`): never reformat applied migrations. The
stack must already be running (`docker compose up -d`, compose project from your local override); verify execs
into it and never restarts it.

Not in verify: the NILM test that needs torch (skipped in the api image; run it in the nilm container) and the
`audit` marked database audits (`-m audit`, audit server only). There is no CI yet: verify plus the full pytest run above are the gate.

## Where things are

| Topic | Doc |
|---|---|
| Services, run, layout, copilot setup | `README.md` |
| Database design and operating rules | `docs/database-design-guide.md`, `docs/database-design.md` |
| Auth | `docs/keycloak-auth.md` |
| Plans and specs before sdlc | `docs/superpowers/{plans,specs}`; new lane L work goes to `docs/work/` |
| Project handoff and debt | sibling web repo: `docs/handoff.md`, `docs/debt.md`; `shortcut:` comments in code |

## Commit messages

Conventional Commits: `<type>(<scope>): <description>`, a concise scope (`db`, `auth`, `billing`, `api`), an
action-oriented description with no trailing period. Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`,
`build`, `ci`, `chore`, `revert`. Examples: `feat(db): initialize public schema modules`,
`refactor(db): split insight and ops revisions`.
