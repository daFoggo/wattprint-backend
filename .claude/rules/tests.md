---
paths:
  - "tests/**"
---

# Tests: rules an agent must not miss

Source of truth: tests/conftest.py, docs/superpowers/plans/2026-11-19-real-dashboard-apis.md ("Lưu ý khi làm tiếp").

- Run the whole suite in the api container (`docker compose exec -T api pytest -q`); it uses the separate `<db>_test` database, never the dev data. One torch-only test skips there (torch is only in the nilm container).
- A test that inserts readings in the past must backfill the aggregates (`app.modules.energy.services.aggregates`).
- A new table or view goes into `tests/db/test_roles.py` `expected_*`.
- Long database audits are marked `audit` and excluded by default (`-m audit` against the audit server only).
