---
paths:
  - "alembic/**"
---

# Migrations: rules an agent must not miss

Source of truth: docs/database-design-guide.md 3.1-3.3. This card is the short version; open the doc when a case is not here.

- Every change is a new hand-written revision (versions/{public,ai,updates}); never edit or reformat an applied one. The DB must build from an empty volume with no manual step.
- Continuous aggregates are created `WITH NO DATA`; refresh only in `autocommit_block()`, never in the migration transaction or a SQL function.
- Hypertable PK contains the time column; no FK into `tb_reading`/`tb_device_estimate`; no secondary index unless a measured query needs it; retention is a `drop_chunks` policy, never `DELETE`.
- Aggregate 1m `compress_after` (14 d) must stay larger than its refresh `start_offset` (7 d).
- A new table or view needs its grants in the role matrix and in `tests/db/test_roles.py` (`expected_*`); copilot reads only `copilot_ro` views.
- Money is `numeric`, power `real`, energy `double precision`; every timestamp is `timestamptz`.
- The running api (dev and prod, uvicorn --reload on the bind-mounted code) picks up model edits at once: write and apply an additive migration BEFORE adding its column to a model (2026-11-28: a prod request got a 500 in the gap).
