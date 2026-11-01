# Database audit

## Findings during build

Task 4 (continuous aggregates), TimescaleDB 2.31.0 on PG17:

- `time_bucket('1 day', bucket, 'Asia/Ho_Chi_Minh')` is accepted on a hierarchical aggregate
  (`reading_1d` over `reading_1h`); the `origin => '2000-01-01 17:00:00+00'` fallback was not
  needed. Readings at 16:59:59 and 17:00:00 UTC land in different daily buckets.
- The predicate `WHERE quality & 1 = 0` is accepted in the `reading_1m` definition.
- `ops.backfill_aggregates` cannot be an SQL procedure: `refresh_continuous_aggregate()` fails
  with "cannot be executed from a function" even via `CALL` from plpgsql. The helper is the
  Python function `app.services.aggregates.backfill_aggregates(conn, from_ts, to_ts)`; it
  requires tz-aware datetimes and an AUTOCOMMIT connection.
- A refresh window must contain at least one whole bucket ("refresh window too small"). The
  helper widens the start down to a bucket boundary per view (daily buckets are cut at 17:00
  UTC) and ends each view at the last CLOSED bucket (`min(ceil(to_ts), floor(now))`), skipping
  views with an empty window. Rounding the end up would materialize the open current bucket and
  move the watermark past now: real-time aggregation then stops covering it and the row stays
  frozen at the backfill-time value until a refresh covers the closed bucket (the 1 d policy
  window `[now-60d, now-1h]` only refreshes whole buckets). With the cap, `to_ts = now` leaves
  the current hour/day served live; this is tested.
- The invalidation threshold only advances as far as the newest raw row, so a late row older
  than the policy `start_offset` is absent until a backfill covers it, but only once newer data
  exists in the same hypertable.
- `add_continuous_aggregate_policy(..., if_not_exists => true)` does not update the offsets of
  an existing policy; a later revision that changes them must remove and re-add the policy.
- Cagg retention jobs appear in `timescaledb_information.jobs` with `hypertable_schema =
  'energy'` and `hypertable_name = '<view>'`; queries on raw-table jobs must filter by name.
