# Database audit

## Findings during build

Task 4 (continuous aggregates), TimescaleDB 2.31.0 on PG17:

- `time_bucket('1 day', bucket, 'Asia/Ho_Chi_Minh')` is accepted on a hierarchical aggregate
  (`reading_1d` over `reading_1h`); the `origin => '2000-01-01 17:00:00+00'` fallback was not
  needed. Readings at 16:59:59 and 17:00:00 UTC land in different daily buckets.
- The predicate `WHERE quality & 1 = 0` is accepted in the `reading_1m` definition.
- `ops.backfill_aggregates` cannot be an SQL procedure: `refresh_continuous_aggregate()` fails
  with "cannot be executed from a function" even via `CALL` from plpgsql. The helper is the
  Python function `app.services.aggregates.backfill_aggregates(conn, from_ts, to_ts)` on an
  AUTOCOMMIT connection.
- A refresh window must contain at least one whole bucket ("refresh window too small"); the
  helper widens the window per view to bucket boundaries (daily buckets are cut at 17:00 UTC).
  A window ending after "now" on the daily view moves its watermark ahead of now.
- The invalidation threshold only advances as far as the newest raw row, so a late row older
  than the policy `start_offset` is absent until a backfill covers it, but only once newer data
  exists in the same hypertable.
- Cagg retention jobs appear in `timescaledb_information.jobs` with `hypertable_schema =
  'energy'` and `hypertable_name = '<view>'`; queries on raw-table jobs must filter by name.
