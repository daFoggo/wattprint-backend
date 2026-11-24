# Plan

| # | Change | Files | Proof |
| --- | --- | --- | --- |
| 1 | viewer role | alembic/versions/public/<new>.py, home/models/model_home_member.py, home/schemas/schema_home.py | migration up/down on the test DB |
| 2 | view endpoint, drop session | auth/services/demo.py, auth/routes/demo.py, auth/schemas/schema_demo.py, auth/utils/exceptions.py, app/config.py | tests/test_demo_api.py rewritten first (404, 409, insert, move, 401) |
| 3 | read-only guard | home/dependencies.py, home/api.py, home/utils, insight/routes/{alerts,watches}.py, copilot/routes/copilot.py | tests: viewer gets 403 on each write, member does not |
| 4 | copilot write tools | copilot/services/tools.py (Ctx.read_only), copilot/services/chat.py | test: viewer create_watch/propose_plan write nothing |
| 5 | mail skips viewers | insight/services/mail.py | test: viewer not in recipients |
| 6 | realm/compose/docs | keycloak/realm/wattprint-realm.json, docker-compose.yml, .env.example, README.md, docs/keycloak-auth.md, .claude/rules/auth.md, tests/test_api.py PUBLIC | test_api |
| 7 | web | features/home schemas, features/auth (actions, server, dialog), NoHome picker, viewer strip, hide writes, packages/auth signInWithTokens removal | vitest + Playwright signed in as a new account |
| 8 | cutover | kcadm on the running Keycloak; recreate api | sign in as a fresh account, view, write → 403 |

Standards: .claude/rules/auth.md, data.md, migrations.md, tests.md, copilot.md (backend); dashboard-data.md, auth.md, ui.md, i18n.md (web).
