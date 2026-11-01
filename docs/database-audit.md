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

## Verdicts (Task 10a, written by hand)

Data: REFIT houses 1-3 through the production ingest path (196.9 M readings, 177.2 M
`device_estimate` rows), dates shifted to end on 2026-10-31, policies OFF during the load.
Numbers: the generated block at the end of this file and `docs/audit-results.json`.

- **Idempotency: PASS.** Reloading 1,000,000 readings of House 1: 0 new, 1,000,000 duplicates,
  `reading` count and a checksum of `reading_1d` unchanged, also on compressed chunks.
- **Correctness gate (1% per home-day): FAIL.** 507 of 1,359 days with coverage >= 95% differ by
  more than 1% (house 1: 129/512, house 2: 152/432, house 3: 226/415; max 54%, p95 1.9-5.4%).
  The view reads HIGHER than the reference on almost every day (signed error recorded:
  house 1 482 of 512 days higher). `test_energy_gate_one_percent` is an xfail carrying these
  numbers and fails if the result gets worse than the recorded `energy_gate_baseline`.
  Coverage reporting itself is correct: `covered_minutes` equals the independent minute count on
  every day (0 mismatches), so low-coverage days show their low coverage.
- **Reference method (spec section 9):** zero-order-hold integration of the raw samples per
  Asia/Ho_Chi_Minh day, `dt = least(next ts - ts, 5 x median cadence)` (median 7.0 s, cap 35 s),
  only samples with `quality & 1 = 0` contribute (flagged time is missing time), gate applied to
  days with `covered_minutes / 1440 >= 0.95`.
- **Cause (variants in `energy_variants_*`):** (a) the meters log about once per 62 s for long
  stretches, which the 35 s cap treats as missing while `energy_wh` counts a full minute for every
  minute with a sample; (b) `Issues`-flagged samples are missing time in the reference but the
  minute average covers them in the view. Relaxing both (hold across flagged, cap 120 s) leaves
  max error 3.7-4.4% and p95 0.8-1.2% (16-30 days per house still over 1%, not investigated).
  Worked examples with exact vs view values: stage `energy_examples` below.
- **Decision requested from the spec owner:** either change the reference (cap expressed in
  minutes, flagged time handled like the view) or change the `energy_wh` rule, then re-measure;
  the 1% gate cannot be called passed with the current definitions.
- **Compression: 17x** on both raw hypertables (reading 18.8 GB -> 1.1 GB, 5.6 bytes per reading);
  day-level results identical before and after (30 sampled days per house).
- **Storage concern:** the continuous aggregates are NOT compressed: 6.5 GB, 3x the compressed raw
  data (`reading_1m` about 151 bytes per row, 3.36 GB); 23 bytes per reading including aggregates.
- **Backfill cost concern:** refreshing the 1 d aggregates took 1,478-1,621 s against 21 s for 1 h
  over the same data (cause not investigated); relevant for the hourly 1 d refresh policy.
- **Caveat:** `alembic upgrade head` switches all policies ON (migration c8a4e1f7b295, retention
  400 days). Loading history requires `ops.set_policies(false)` first. The audit harness refuses
  to run unless the database name starts with `wattprint_audit` and `AUDIT_ADMIN_URL` is set.

## Verdicts (Task 10b, written by hand)

Per spec section 9 criterion. Houses 4-20 were NOT loaded (ruling: extrapolate from houses 1-3;
a full 20-house load is the user's later decision). Numbers: stages `latency`, `drills`,
`isolation`, `rebuild`, `refresh_cost`, `cagg_compression`, `policy_drill`, `extrapolation`,
`harness_check` in the generated block.

| # | Criterion | Verdict |
|---|---|---|
| 1 | Idempotency | PASS (10a) |
| 2 | Correctness, 1% per home-day | FAIL (10a, decision open, see above) |
| 3 | Read latency | PASS on 3 houses |
| 4 | Ingest throughput and growth | MEASURED for 3 houses, extrapolated beyond |
| 5 | Failure drills | PASS (5 of 5) |
| 6 | Isolation | PASS |
| 7 | Rebuild from empty | PASS |

- **Latency: PASS.** Data compressed, policies off, 30 runs per case, each new session. p95 in ms
  (warm / varied windows): series 1d over 90 d 4.5 / 3.7, 6h over 90 d 5.3 / 5.0, 1h over 45 d
  6.0 / 5.0, 5m over 1 d 4.9 / 5.6, `latest_power` 2.4 / 3.5 (target 20), device breakdown 1 d
  2.9 / 3.2 and 30 d 4.2 / 3.5, `compute_bill` 17.5 / 17.8 (target 100 for all but `latest_power`).
  After a server restart the first calls were 2.6-48 ms (OS page cache stays warm, so this is
  not a disk-cold figure). Lagging watermark (1.5 h of raw rows newer than every watermark, so the
  real-time part runs): p95 1.9 `latest_power`, 4.4-5.1 series; the real-time branch scans 2 chunks
  and costs under 2 ms. Plans: `EXPLAIN (ANALYZE, BUFFERS)` trimmed in `latency.*.plans`; every
  read touches only aggregate chunks (1-12 chunk relations, 0 shared reads). Limit: only 3 homes and
  22 M 1 m rows; the plans are index/bitmap scans on `(series_id, bucket)` so cost should stay flat
  per series, but a 10,000-home table was not measured.
- **Failure drills: PASS.** Duplicate batch (0 new, aggregates unchanged), out-of-order and late
  batch inside a materialized range (picked up by `backfill_aggregates`, checkpoint never moves
  back), a 90 minute gap (no row, no fill, `covered_minutes` 60 of 120), `Issues`-flagged rows
  (kept in raw, excluded from the aggregates), refresh jobs paused (new data is served by
  real-time aggregation with the exact expected energy while nothing is materialized).
- **Isolation: PASS** on the loaded audit database (2 homes, 15 views, token variants, no direct
  table access, no writes).
- **Rebuild: PASS.** Empty database, `alembic upgrade head`, `app.cli.load_refit --house 1
  --limit-rows 10000`: 100,000 readings, 10 series, tariff and catalog seeded, no manual step.
  (Policies are ON after the migration, 12 jobs.)
- **Growth and extrapolation (assumptions in `extrapolation.assumptions`):** the spec gives no
  sampling rate, so three scenarios per 10,000 homes: REFIT-like 10 series at 7 s = 1.23 G rows/day
  (14.3k rows/s average, 0.29 of one measured 49.6k rows/s stream) and 3.1 TB/year with the 1 m
  aggregate compressed, 10.6 TB uncompressed; main meter only at 1 Hz = 864 M rows/day (10k rows/s)
  and 1.8 TB/year compressed (2.6 uncompressed); 10 series at 30 s with 9 estimates = 288 M rows/day
  and 1.7 TB/year compressed (9.2 uncompressed). Averages only: no peak factor, no raw retention
  applied, compression 17x assumed for all cadences, every minute assumed covered (upper bound;
  measured REFIT is 0.88 GB per home-year against 1.06 predicted). One writer stream sustains
  the average rate of all three scenarios; concurrency under 10,000 live meters was not tested.
- **1 m aggregate compression (evaluated on a scratch copy, not applied): recommended.**
  `ALTER MATERIALIZED VIEW ... SET (timescaledb.compress, segmentby series_id, orderby bucket DESC)`
  on one month of House 1: `reading_1m` 147.8 -> 7.7 bytes/row (19.1x), `device_estimate_1m`
  147.2 -> 6.4 (23.1x), row counts unchanged, 1 m reads on compressed chunks 1.4-2.0 ms p95. It is a
  small migration (plus a compression policy for the cagg); not made in this task. Applied to the
  audit data it would take the 6.5 GB of aggregates to about 0.3 GB.
- **Why the 1 d backfill was slow (10a open question): answered.** A forced refresh of 30 days
  costs 0.09 s for 1 d and 1.1 s for 1 h on the audit data, and one invalidated day or a
  policy-sized window refreshes in 7-16 ms. The cost appears only while newer raw data is not yet
  materialized: on a scratch copy the 1 d refresh of a 30-day window took 0.07 s alone, 6.5 s with
  four more months of unmaterialized raw data present, and 0.04 s again when `reading_1m` and
  `reading_1h` were set `materialized_only` (the real-time branch of the source views is evaluated
  during the refresh). So the 1 d refresh scales with the amount of raw data newer than the
  window: a backfill of a long history should either run newest-first, or switch the 1 m/1 h views to
  `materialized_only` for its duration. In steady state (policy windows) the cost is negligible.
- **Retention and aggregates (scratch drill, jobs paused and run by hand):** the raw 400-day
  retention drops the raw chunks of the old range and leaves 1 m, 1 h and 1 d buckets untouched; the
  refresh policies (7 d / 30 d / 60 d) do not touch old buckets; the 1 m retention job (set by
  `ops.set_policies`) deletes only the old 1 m buckets, so 1 h and 1 d survive indefinitely as the
  spec intends and need no retention policy. **Risk found:** a manual `backfill_aggregates` over a range
  whose raw chunks were already dropped DELETES the existing 1 m, 1 h and 1 d buckets of that range
  (all three went to 0 rows). Never backfill a window older than the raw retention.
  Compression policy and policy jobs fire immediately after `set_policies(true)` on the background
  scheduler (new jobs start at once), which is why the drill pauses them first.
- **Harness check:** a limited end-to-end run on a scratch database (load, backfill, compress)
  confirmed both fixed bugs (compressed chunk count 15 = database, per-view timing keys are view
  names) and exposed a third one, fixed: `compress` crashed when a hypertable had no compressed
  chunk (no statistics row).
- **Docker VM disk:** 1.08 TB total, 0.96 TB free at the end (`env.docker_vm_disk_bytes`).
- **Side effect on the audit data:** the refresh-cost drill re-materialized two days of House 1
  (restored; per-row diff against a snapshot taken before the drill: 0 rows changed). The row digest
  of `reading_1d` recorded in 10a differs from today's digest although all sums are equal
  (earlier unsnapshotted drill runs, probably last-digit float differences in the two recomputed
  days); compare digests only within one run.

<!-- audit:begin -->
## Measured results

Generated by `python -m tests.audit.run report` from `docs/audit-results.json`; do not edit this block by hand.

### backfill

| key | value |
|---|---|
| `aggregate_rows.energy.device_estimate_1d` | 14,706 |
| `aggregate_rows.energy.device_estimate_1h` | 342,054 |
| `aggregate_rows.energy.device_estimate_1m` | 20,325,051 |
| `aggregate_rows.energy.reading_1d` | 16,340 |
| `aggregate_rows.energy.reading_1h` | 378,670 |
| `aggregate_rows.energy.reading_1m` | 22,185,510 |
| `note` | per-view seconds were summed BY HAND (a one-off script) after the run from the per-window timings the first harness version stored under the full parameter tuple; they add up to total_seconds. The harness is fixed for future runs, not re-run. |
| `range` | 2025-01-30T00:00:00+00:00, 2026-11-01T00:00:00+00:00 |
| `refresh_seconds_per_view.energy.device_estimate_1d` | 1,478 |
| `refresh_seconds_per_view.energy.device_estimate_1h` | 21.4 |
| `refresh_seconds_per_view.energy.device_estimate_1m` | 675.9 |
| `refresh_seconds_per_view.energy.reading_1d` | 1,621 |
| `refresh_seconds_per_view.energy.reading_1h` | 21.3 |
| `refresh_seconds_per_view.energy.reading_1m` | 697.3 |
| `total_seconds` | 4,517 |

### cagg_compression

| key | value |
|---|---|
| `backfill_seconds` | 30.8 |
| `backfill_seconds_per_view.energy.device_estimate_1d` | 0.05 |
| `backfill_seconds_per_view.energy.device_estimate_1h` | 0.51 |
| `backfill_seconds_per_view.energy.device_estimate_1m` | 14.49 |
| `backfill_seconds_per_view.energy.reading_1d` | 0.05 |
| `backfill_seconds_per_view.energy.reading_1h` | 0.51 |
| `backfill_seconds_per_view.energy.reading_1m` | 15.15 |
| `copied_rows.device_estimate` | 2,231,649 |
| `copied_rows.reading` | 2,479,610 |
| `device_estimate_1m.bytes_after` | 1,589,248 |
| `device_estimate_1m.bytes_before` | 36,691,968 |
| `device_estimate_1m.bytes_per_row_after` | 6.4 |
| `device_estimate_1m.bytes_per_row_before` | 147.2 |
| `device_estimate_1m.chunks_compressed` | 3 |
| `device_estimate_1m.compress_seconds` | 0.2 |
| `device_estimate_1m.ratio` | 23.09 |
| `device_estimate_1m.row_count_unchanged` | True |
| `device_estimate_1m.rows` | 249,255 |
| `latency_on_compressed_1m_ms.5m_over_1d.max_ms` | 2.05 |
| `latency_on_compressed_1m_ms.5m_over_1d.n` | 30 |
| `latency_on_compressed_1m_ms.5m_over_1d.p50_ms` | 1.35 |
| `latency_on_compressed_1m_ms.5m_over_1d.p95_ms` | 1.99 |
| `latency_on_compressed_1m_ms.latest_minute.max_ms` | 1.64 |
| `latency_on_compressed_1m_ms.latest_minute.n` | 30 |
| `latency_on_compressed_1m_ms.latest_minute.p50_ms` | 0.49 |
| `latency_on_compressed_1m_ms.latest_minute.p95_ms` | 1.43 |
| `reading_1m.bytes_after` | 2,138,112 |
| `reading_1m.bytes_before` | 40,927,232 |
| `reading_1m.bytes_per_row_after` | 7.7 |
| `reading_1m.bytes_per_row_before` | 147.8 |
| `reading_1m.chunks_compressed` | 3 |
| `reading_1m.compress_seconds` | 0.3 |
| `reading_1m.ratio` | 19.14 |
| `reading_1m.row_count_unchanged` | True |
| `reading_1m.rows` | 276,940 |
| `slice` | House 1, 2026-09 (all series incl. plugs) |

### compress

| key | value |
|---|---|
| `chunks_compressed_this_run` | 1,272 |
| `duration_seconds` | 47.7 |
| `hypertable_size_after_bytes.device_estimate` | 995,926,016 |
| `hypertable_size_after_bytes.reading` | 1,105,944,576 |
| `hypertable_size_before_bytes.device_estimate` | 17,002,078,208 |
| `hypertable_size_before_bytes.reading` | 18,789,769,216 |
| `note` | BY HAND: stats.*.compressed_chunks set to 636 (the first harness version stored 1, the row count of hypertable_compression_stats; real value is number_compressed_chunks, 636 of 638 per table, newest 2 days stay uncompressed) and stats.*.ratio_compressed_chunks converted from a Decimal string to a number. The harness is fixed for future runs, not re-run. |
| `ratio_hypertable_size.device_estimate` | 17.07 |
| `ratio_hypertable_size.reading` | 16.99 |
| `stats.device_estimate.compressed_after_bytes` | 938,262,528 |
| `stats.device_estimate.compressed_before_bytes` | 16,954,834,944 |
| `stats.device_estimate.compressed_chunks` | 636 |
| `stats.device_estimate.ratio_compressed_chunks` | 18.07 |
| `stats.device_estimate.total_chunks` | 638 |
| `stats.reading.compressed_after_bytes` | 1,043,496,960 |
| `stats.reading.compressed_before_bytes` | 18,737,741,824 |
| `stats.reading.compressed_chunks` | 636 |
| `stats.reading.ratio_compressed_chunks` | 17.96 |
| `stats.reading.total_chunks` | 638 |
| `workers` | 4 |

### drills

| key | value |
|---|---|
| `duplicate_batch.covered_minutes` | 60 |
| `duplicate_batch.first_new` | 360 |
| `duplicate_batch.hour_n` | 360 |
| `duplicate_batch.hour_wh` | 600 |
| `duplicate_batch.second_dup` | 360 |
| `duplicate_batch.second_new` | 0 |
| `gap_over_1h.day_covered_minutes` | 60 |
| `gap_over_1h.day_energy_wh` | 600 |
| `gap_over_1h.hour_in_gap_has_row` | False |
| `gap_over_1h.points` | 2026-03-12T03:00:00+00:00, 2026-03-12T05:00:00+00:00 |
| `issues_flagged.covered_minutes` | 30 |
| `issues_flagged.raw_flagged` | 180 |
| `issues_flagged.raw_rows` | 360 |
| `issues_flagged.view_n` | 180 |
| `issues_flagged.view_wh` | 300 |
| `out_of_order.checkpoint_not_moved_back` | True |
| `out_of_order.first_hour_wh` | 600 |
| `out_of_order.late_hour_wh` | 600 |
| `out_of_order.late_rows_new` | 360 |
| `stopped_refresh_job.day_wh` | 600 |
| `stopped_refresh_job.hour_wh` | 600 |
| `stopped_refresh_job.materialized_rows_for_new_hour` | 0 |
| `stopped_refresh_job.points_5m` | 12 |
| `stopped_refresh_job.refresh_jobs_paused` | 6 |

### energy_examples

| key | value |
|---|---|
| `house1_days[0].cause` | irregular cadence: about 62 s logging vs the 35 s cap (reference) while the view counts a full minute per minute with a sample |
| `house1_days[0].cause_source` | manual |
| `house1_days[0].covered_minutes` | 1,397 |
| `house1_days[0].day_start_utc` | 2025-11-22T17:00:00+00:00 |
| `house1_days[0].err_pct` | 53.81 |
| `house1_days[0].flagged_samples` | 2 |
| `house1_days[0].hold_across_flagged_cap_120s_wh` | 5,346 |
| `house1_days[0].hold_across_flagged_wh` | 3,373 |
| `house1_days[0].intervals_over_120s` | 0 |
| `house1_days[0].intervals_over_35s` | 1,152 |
| `house1_days[0].label` | worst day |
| `house1_days[0].max_gap_s` | 117 |
| `house1_days[0].reference_wh` | 3,372 |
| `house1_days[0].samples` | 3,159 |
| `house1_days[0].view_wh` | 5,187 |
| `house1_days[1].cause` | Issues-flagged samples are missing time in the reference, covered in the view |
| `house1_days[1].cause_source` | manual |
| `house1_days[1].covered_minutes` | 1,440 |
| `house1_days[1].day_start_utc` | 2025-08-24T17:00:00+00:00 |
| `house1_days[1].err_pct` | 4.218 |
| `house1_days[1].flagged_samples` | 106 |
| `house1_days[1].hold_across_flagged_cap_120s_wh` | 10,224 |
| `house1_days[1].hold_across_flagged_wh` | 10,185 |
| `house1_days[1].intervals_over_120s` | 0 |
| `house1_days[1].intervals_over_35s` | 0 |
| `house1_days[1].label` | flagged samples only |
| `house1_days[1].max_gap_s` | 33 |
| `house1_days[1].reference_wh` | 9,880 |
| `house1_days[1].samples` | 10,053 |
| `house1_days[1].view_wh` | 10,297 |
| `house1_days[2].cause` | flagged samples plus one 194 s gap |
| `house1_days[2].cause_source` | manual |
| `house1_days[2].covered_minutes` | 1,418 |
| `house1_days[2].day_start_utc` | 2025-04-17T17:00:00+00:00 |
| `house1_days[2].err_pct` | 4.067 |
| `house1_days[2].flagged_samples` | 427 |
| `house1_days[2].hold_across_flagged_cap_120s_wh` | 31,434 |
| `house1_days[2].hold_across_flagged_wh` | 30,779 |
| `house1_days[2].intervals_over_120s` | 1 |
| `house1_days[2].intervals_over_35s` | 1 |
| `house1_days[2].label` | flagged plus one gap |
| `house1_days[2].max_gap_s` | 194 |
| `house1_days[2].reference_wh` | 30,190 |
| `house1_days[2].samples` | 10,006 |
| `house1_days[2].view_wh` | 31,418 |
| `house1_days[3].cause` | gaps agree between reference and view |
| `house1_days[3].cause_source` | manual |
| `house1_days[3].covered_minutes` | 1,408 |
| `house1_days[3].day_start_utc` | 2025-08-25T17:00:00+00:00 |
| `house1_days[3].err_pct` | 0.1783 |
| `house1_days[3].flagged_samples` | 7 |
| `house1_days[3].hold_across_flagged_cap_120s_wh` | 7,640 |
| `house1_days[3].hold_across_flagged_wh` | 7,345 |
| `house1_days[3].intervals_over_120s` | 4 |
| `house1_days[3].intervals_over_35s` | 9 |
| `house1_days[3].label` | control (passes) |
| `house1_days[3].max_gap_s` | 787 |
| `house1_days[3].reference_wh` | 7,341 |
| `house1_days[3].samples` | 11,184 |
| `house1_days[3].view_wh` | 7,354 |

### energy_gate_baseline

| key | value |
|---|---|
| `house1.days_over_gate` | 129 |
| `house1.err_pct_max` | 53.81 |
| `house1.source` | first measurement, pre-compression |
| `house2.days_over_gate` | 152 |
| `house2.err_pct_max` | 45.46 |
| `house2.source` | first measurement, pre-compression |
| `house3.days_over_gate` | 226 |
| `house3.err_pct_max` | 54.2 |
| `house3.source` | first measurement, pre-compression |

### energy_sample

| key | value |
|---|---|
| `days_checked_after_compression` | 90 |
| `identical_after_compression` | True |

### energy_variants_post_compress

| key | value |
|---|---|
| `house1.hold_across_flagged.covered_minutes_mismatch_days` | 0 |
| `house1.hold_across_flagged.exact_days_without_view` |  |
| `house1.hold_across_flagged.exact_days_without_view_count` | 0 |
| `house1.hold_across_flagged.full_coverage.days` | 512 |
| `house1.hold_across_flagged.full_coverage.days_over_gate` | 17 |
| `house1.hold_across_flagged.full_coverage.days_view_higher` | 364 |
| `house1.hold_across_flagged.full_coverage.days_view_lower` | 148 |
| `house1.hold_across_flagged.full_coverage.err_pct_max` | 53.77 |
| `house1.hold_across_flagged.full_coverage.err_pct_p50` | 0.1349 |
| `house1.hold_across_flagged.full_coverage.err_pct_p95` | 0.8156 |
| `house1.hold_across_flagged.full_coverage.err_pct_p99` | 1.987 |
| `house1.hold_across_flagged.full_coverage.signed_err_pct_mean` | 0.287 |
| `house1.hold_across_flagged.full_coverage.signed_err_pct_p50` | 0.09707 |
| `house1.hold_across_flagged.low_coverage.days` | 68 |
| `house1.hold_across_flagged.low_coverage.days_over_gate` | 9 |
| `house1.hold_across_flagged.low_coverage.days_view_higher` | 50 |
| `house1.hold_across_flagged.low_coverage.days_view_lower` | 18 |
| `house1.hold_across_flagged.low_coverage.err_pct_max` | 48.29 |
| `house1.hold_across_flagged.low_coverage.err_pct_p50` | 0.2634 |
| `house1.hold_across_flagged.low_coverage.err_pct_p95` | 3.516 |
| `house1.hold_across_flagged.low_coverage.err_pct_p99` | 21.38 |
| `house1.hold_across_flagged.low_coverage.signed_err_pct_mean` | 1.287 |
| `house1.hold_across_flagged.low_coverage.signed_err_pct_p50` | 0.2211 |
| `house1.hold_across_flagged.view_days_without_exact` |  |
| `house1.hold_across_flagged_cap_120s.covered_minutes_mismatch_days` | 0 |
| `house1.hold_across_flagged_cap_120s.exact_days_without_view` |  |
| `house1.hold_across_flagged_cap_120s.exact_days_without_view_count` | 0 |
| `house1.hold_across_flagged_cap_120s.full_coverage.days` | 512 |
| `house1.hold_across_flagged_cap_120s.full_coverage.days_over_gate` | 19 |
| `house1.hold_across_flagged_cap_120s.full_coverage.days_view_higher` | 194 |
| `house1.hold_across_flagged_cap_120s.full_coverage.days_view_lower` | 318 |
| `house1.hold_across_flagged_cap_120s.full_coverage.err_pct_max` | 3.741 |
| `house1.hold_across_flagged_cap_120s.full_coverage.err_pct_p50` | 0.1472 |
| `house1.hold_across_flagged_cap_120s.full_coverage.err_pct_p95` | 0.7951 |
| `house1.hold_across_flagged_cap_120s.full_coverage.err_pct_p99` | 2.942 |
| `house1.hold_across_flagged_cap_120s.full_coverage.signed_err_pct_mean` | -0.1267 |
| `house1.hold_across_flagged_cap_120s.full_coverage.signed_err_pct_p50` | -0.05422 |
| `house1.hold_across_flagged_cap_120s.low_coverage.days` | 68 |
| `house1.hold_across_flagged_cap_120s.low_coverage.days_over_gate` | 20 |
| `house1.hold_across_flagged_cap_120s.low_coverage.days_view_higher` | 10 |
| `house1.hold_across_flagged_cap_120s.low_coverage.days_view_lower` | 58 |
| `house1.hold_across_flagged_cap_120s.low_coverage.err_pct_max` | 10.05 |
| `house1.hold_across_flagged_cap_120s.low_coverage.err_pct_p50` | 0.4206 |
| `house1.hold_across_flagged_cap_120s.low_coverage.err_pct_p95` | 2.784 |
| `house1.hold_across_flagged_cap_120s.low_coverage.err_pct_p99` | 8.756 |
| `house1.hold_across_flagged_cap_120s.low_coverage.signed_err_pct_mean` | -0.7087 |
| `house1.hold_across_flagged_cap_120s.low_coverage.signed_err_pct_p50` | -0.3759 |
| `house1.hold_across_flagged_cap_120s.view_days_without_exact` |  |
| `house2.hold_across_flagged.covered_minutes_mismatch_days` | 0 |
| `house2.hold_across_flagged.exact_days_without_view` |  |
| `house2.hold_across_flagged.exact_days_without_view_count` | 0 |
| `house2.hold_across_flagged.full_coverage.days` | 432 |
| `house2.hold_across_flagged.full_coverage.days_over_gate` | 31 |
| `house2.hold_across_flagged.full_coverage.days_view_higher` | 325 |
| `house2.hold_across_flagged.full_coverage.days_view_lower` | 107 |
| `house2.hold_across_flagged.full_coverage.err_pct_max` | 45.03 |
| `house2.hold_across_flagged.full_coverage.err_pct_p50` | 0.2183 |
| `house2.hold_across_flagged.full_coverage.err_pct_p95` | 1.066 |
| `house2.hold_across_flagged.full_coverage.err_pct_p99` | 1.451 |
| `house2.hold_across_flagged.full_coverage.signed_err_pct_mean` | 0.3988 |
| `house2.hold_across_flagged.full_coverage.signed_err_pct_p50` | 0.1526 |
| `house2.hold_across_flagged.low_coverage.days` | 60 |
| `house2.hold_across_flagged.low_coverage.days_over_gate` | 17 |
| `house2.hold_across_flagged.low_coverage.days_view_higher` | 50 |
| `house2.hold_across_flagged.low_coverage.days_view_lower` | 10 |
| `house2.hold_across_flagged.low_coverage.err_pct_max` | 12.11 |
| `house2.hold_across_flagged.low_coverage.err_pct_p50` | 0.4771 |
| `house2.hold_across_flagged.low_coverage.err_pct_p95` | 6.553 |
| `house2.hold_across_flagged.low_coverage.err_pct_p99` | 10.07 |
| `house2.hold_across_flagged.low_coverage.signed_err_pct_mean` | 1.55 |
| `house2.hold_across_flagged.low_coverage.signed_err_pct_p50` | 0.4386 |
| `house2.hold_across_flagged.view_days_without_exact` |  |
| `house2.hold_across_flagged_cap_120s.covered_minutes_mismatch_days` | 0 |
| `house2.hold_across_flagged_cap_120s.exact_days_without_view` |  |
| `house2.hold_across_flagged_cap_120s.exact_days_without_view_count` | 0 |
| `house2.hold_across_flagged_cap_120s.full_coverage.days` | 432 |
| `house2.hold_across_flagged_cap_120s.full_coverage.days_over_gate` | 16 |
| `house2.hold_across_flagged_cap_120s.full_coverage.days_view_higher` | 264 |
| `house2.hold_across_flagged_cap_120s.full_coverage.days_view_lower` | 168 |
| `house2.hold_across_flagged_cap_120s.full_coverage.err_pct_max` | 2.355 |
| `house2.hold_across_flagged_cap_120s.full_coverage.err_pct_p50` | 0.1787 |
| `house2.hold_across_flagged_cap_120s.full_coverage.err_pct_p95` | 0.9205 |
| `house2.hold_across_flagged_cap_120s.full_coverage.err_pct_p99` | 1.261 |
| `house2.hold_across_flagged_cap_120s.full_coverage.signed_err_pct_mean` | 0.148 |
| `house2.hold_across_flagged_cap_120s.full_coverage.signed_err_pct_p50` | 0.0445 |
| `house2.hold_across_flagged_cap_120s.low_coverage.days` | 60 |
| `house2.hold_across_flagged_cap_120s.low_coverage.days_over_gate` | 19 |
| `house2.hold_across_flagged_cap_120s.low_coverage.days_view_higher` | 17 |
| `house2.hold_across_flagged_cap_120s.low_coverage.days_view_lower` | 43 |
| `house2.hold_across_flagged_cap_120s.low_coverage.err_pct_max` | 28.07 |
| `house2.hold_across_flagged_cap_120s.low_coverage.err_pct_p50` | 0.5956 |
| `house2.hold_across_flagged_cap_120s.low_coverage.err_pct_p95` | 24.29 |
| `house2.hold_across_flagged_cap_120s.low_coverage.err_pct_p99` | 26.29 |
| `house2.hold_across_flagged_cap_120s.low_coverage.signed_err_pct_mean` | -3.44 |
| `house2.hold_across_flagged_cap_120s.low_coverage.signed_err_pct_p50` | -0.3756 |
| `house2.hold_across_flagged_cap_120s.view_days_without_exact` |  |
| `house3.hold_across_flagged.covered_minutes_mismatch_days` | 0 |
| `house3.hold_across_flagged.exact_days_without_view` |  |
| `house3.hold_across_flagged.exact_days_without_view_count` | 0 |
| `house3.hold_across_flagged.full_coverage.days` | 415 |
| `house3.hold_across_flagged.full_coverage.days_over_gate` | 64 |
| `house3.hold_across_flagged.full_coverage.days_view_higher` | 369 |
| `house3.hold_across_flagged.full_coverage.days_view_lower` | 46 |
| `house3.hold_across_flagged.full_coverage.err_pct_max` | 54.14 |
| `house3.hold_across_flagged.full_coverage.err_pct_p50` | 0.3003 |
| `house3.hold_across_flagged.full_coverage.err_pct_p95` | 1.84 |
| `house3.hold_across_flagged.full_coverage.err_pct_p99` | 3.831 |
| `house3.hold_across_flagged.full_coverage.signed_err_pct_mean` | 0.6679 |
| `house3.hold_across_flagged.full_coverage.signed_err_pct_p50` | 0.2964 |
| `house3.hold_across_flagged.low_coverage.days` | 147 |
| `house3.hold_across_flagged.low_coverage.days_over_gate` | 78 |
| `house3.hold_across_flagged.low_coverage.days_view_higher` | 141 |
| `house3.hold_across_flagged.low_coverage.days_view_lower` | 6 |
| `house3.hold_across_flagged.low_coverage.err_pct_max` | 38.65 |
| `house3.hold_across_flagged.low_coverage.err_pct_p50` | 1.075 |
| `house3.hold_across_flagged.low_coverage.err_pct_p95` | 4.716 |
| `house3.hold_across_flagged.low_coverage.err_pct_p99` | 10.58 |
| `house3.hold_across_flagged.low_coverage.signed_err_pct_mean` | 1.926 |
| `house3.hold_across_flagged.low_coverage.signed_err_pct_p50` | 1.075 |
| `house3.hold_across_flagged.view_days_without_exact` |  |
| `house3.hold_across_flagged_cap_120s.covered_minutes_mismatch_days` | 0 |
| `house3.hold_across_flagged_cap_120s.exact_days_without_view` |  |
| `house3.hold_across_flagged_cap_120s.exact_days_without_view_count` | 0 |
| `house3.hold_across_flagged_cap_120s.full_coverage.days` | 415 |
| `house3.hold_across_flagged_cap_120s.full_coverage.days_over_gate` | 30 |
| `house3.hold_across_flagged_cap_120s.full_coverage.days_view_higher` | 254 |
| `house3.hold_across_flagged_cap_120s.full_coverage.days_view_lower` | 161 |
| `house3.hold_across_flagged_cap_120s.full_coverage.err_pct_max` | 4.379 |
| `house3.hold_across_flagged_cap_120s.full_coverage.err_pct_p50` | 0.2053 |
| `house3.hold_across_flagged_cap_120s.full_coverage.err_pct_p95` | 1.223 |
| `house3.hold_across_flagged_cap_120s.full_coverage.err_pct_p99` | 2.997 |
| `house3.hold_across_flagged_cap_120s.full_coverage.signed_err_pct_mean` | 0.05479 |
| `house3.hold_across_flagged_cap_120s.full_coverage.signed_err_pct_p50` | 0.06029 |
| `house3.hold_across_flagged_cap_120s.low_coverage.days` | 147 |
| `house3.hold_across_flagged_cap_120s.low_coverage.days_over_gate` | 76 |
| `house3.hold_across_flagged_cap_120s.low_coverage.days_view_higher` | 18 |
| `house3.hold_across_flagged_cap_120s.low_coverage.days_view_lower` | 129 |
| `house3.hold_across_flagged_cap_120s.low_coverage.err_pct_max` | 11.93 |
| `house3.hold_across_flagged_cap_120s.low_coverage.err_pct_p50` | 1.029 |
| `house3.hold_across_flagged_cap_120s.low_coverage.err_pct_p95` | 6.938 |
| `house3.hold_across_flagged_cap_120s.low_coverage.err_pct_p99` | 11.38 |
| `house3.hold_across_flagged_cap_120s.low_coverage.signed_err_pct_mean` | -1.646 |
| `house3.hold_across_flagged_cap_120s.low_coverage.signed_err_pct_p50` | -1.005 |
| `house3.hold_across_flagged_cap_120s.view_days_without_exact` |  |

### energy_variants_pre_compress

| key | value |
|---|---|
| `house1.hold_across_flagged.covered_minutes_mismatch_days` | 0 |
| `house1.hold_across_flagged.full_coverage.days` | 512 |
| `house1.hold_across_flagged.full_coverage.days_over_gate` | 17 |
| `house1.hold_across_flagged.full_coverage.err_pct_max` | 53.77 |
| `house1.hold_across_flagged.full_coverage.err_pct_p50` | 0.1349 |
| `house1.hold_across_flagged.full_coverage.err_pct_p95` | 0.8156 |
| `house1.hold_across_flagged.full_coverage.err_pct_p99` | 1.987 |
| `house1.hold_across_flagged.low_coverage.days` | 68 |
| `house1.hold_across_flagged.low_coverage.days_over_gate` | 9 |
| `house1.hold_across_flagged.low_coverage.err_pct_max` | 48.29 |
| `house1.hold_across_flagged.low_coverage.err_pct_p50` | 0.2634 |
| `house1.hold_across_flagged.low_coverage.err_pct_p95` | 3.516 |
| `house1.hold_across_flagged.low_coverage.err_pct_p99` | 21.38 |
| `house1.hold_across_flagged.view_days_without_exact` |  |
| `house1.hold_across_flagged_cap_120s.covered_minutes_mismatch_days` | 0 |
| `house1.hold_across_flagged_cap_120s.full_coverage.days` | 512 |
| `house1.hold_across_flagged_cap_120s.full_coverage.days_over_gate` | 19 |
| `house1.hold_across_flagged_cap_120s.full_coverage.err_pct_max` | 3.741 |
| `house1.hold_across_flagged_cap_120s.full_coverage.err_pct_p50` | 0.1472 |
| `house1.hold_across_flagged_cap_120s.full_coverage.err_pct_p95` | 0.7951 |
| `house1.hold_across_flagged_cap_120s.full_coverage.err_pct_p99` | 2.942 |
| `house1.hold_across_flagged_cap_120s.low_coverage.days` | 68 |
| `house1.hold_across_flagged_cap_120s.low_coverage.days_over_gate` | 20 |
| `house1.hold_across_flagged_cap_120s.low_coverage.err_pct_max` | 10.05 |
| `house1.hold_across_flagged_cap_120s.low_coverage.err_pct_p50` | 0.4206 |
| `house1.hold_across_flagged_cap_120s.low_coverage.err_pct_p95` | 2.784 |
| `house1.hold_across_flagged_cap_120s.low_coverage.err_pct_p99` | 8.756 |
| `house1.hold_across_flagged_cap_120s.view_days_without_exact` |  |
| `house2.hold_across_flagged.covered_minutes_mismatch_days` | 0 |
| `house2.hold_across_flagged.full_coverage.days` | 432 |
| `house2.hold_across_flagged.full_coverage.days_over_gate` | 31 |
| `house2.hold_across_flagged.full_coverage.err_pct_max` | 45.03 |
| `house2.hold_across_flagged.full_coverage.err_pct_p50` | 0.2183 |
| `house2.hold_across_flagged.full_coverage.err_pct_p95` | 1.066 |
| `house2.hold_across_flagged.full_coverage.err_pct_p99` | 1.451 |
| `house2.hold_across_flagged.low_coverage.days` | 60 |
| `house2.hold_across_flagged.low_coverage.days_over_gate` | 17 |
| `house2.hold_across_flagged.low_coverage.err_pct_max` | 12.11 |
| `house2.hold_across_flagged.low_coverage.err_pct_p50` | 0.4771 |
| `house2.hold_across_flagged.low_coverage.err_pct_p95` | 6.553 |
| `house2.hold_across_flagged.low_coverage.err_pct_p99` | 10.07 |
| `house2.hold_across_flagged.view_days_without_exact` |  |
| `house2.hold_across_flagged_cap_120s.covered_minutes_mismatch_days` | 0 |
| `house2.hold_across_flagged_cap_120s.full_coverage.days` | 432 |
| `house2.hold_across_flagged_cap_120s.full_coverage.days_over_gate` | 16 |
| `house2.hold_across_flagged_cap_120s.full_coverage.err_pct_max` | 2.355 |
| `house2.hold_across_flagged_cap_120s.full_coverage.err_pct_p50` | 0.1787 |
| `house2.hold_across_flagged_cap_120s.full_coverage.err_pct_p95` | 0.9205 |
| `house2.hold_across_flagged_cap_120s.full_coverage.err_pct_p99` | 1.261 |
| `house2.hold_across_flagged_cap_120s.low_coverage.days` | 60 |
| `house2.hold_across_flagged_cap_120s.low_coverage.days_over_gate` | 19 |
| `house2.hold_across_flagged_cap_120s.low_coverage.err_pct_max` | 28.07 |
| `house2.hold_across_flagged_cap_120s.low_coverage.err_pct_p50` | 0.5956 |
| `house2.hold_across_flagged_cap_120s.low_coverage.err_pct_p95` | 24.29 |
| `house2.hold_across_flagged_cap_120s.low_coverage.err_pct_p99` | 26.29 |
| `house2.hold_across_flagged_cap_120s.view_days_without_exact` |  |
| `house3.hold_across_flagged.covered_minutes_mismatch_days` | 0 |
| `house3.hold_across_flagged.full_coverage.days` | 415 |
| `house3.hold_across_flagged.full_coverage.days_over_gate` | 64 |
| `house3.hold_across_flagged.full_coverage.err_pct_max` | 54.14 |
| `house3.hold_across_flagged.full_coverage.err_pct_p50` | 0.3003 |
| `house3.hold_across_flagged.full_coverage.err_pct_p95` | 1.84 |
| `house3.hold_across_flagged.full_coverage.err_pct_p99` | 3.831 |
| `house3.hold_across_flagged.low_coverage.days` | 147 |
| `house3.hold_across_flagged.low_coverage.days_over_gate` | 78 |
| `house3.hold_across_flagged.low_coverage.err_pct_max` | 38.65 |
| `house3.hold_across_flagged.low_coverage.err_pct_p50` | 1.075 |
| `house3.hold_across_flagged.low_coverage.err_pct_p95` | 4.716 |
| `house3.hold_across_flagged.low_coverage.err_pct_p99` | 10.58 |
| `house3.hold_across_flagged.view_days_without_exact` |  |
| `house3.hold_across_flagged_cap_120s.covered_minutes_mismatch_days` | 0 |
| `house3.hold_across_flagged_cap_120s.full_coverage.days` | 415 |
| `house3.hold_across_flagged_cap_120s.full_coverage.days_over_gate` | 30 |
| `house3.hold_across_flagged_cap_120s.full_coverage.err_pct_max` | 4.379 |
| `house3.hold_across_flagged_cap_120s.full_coverage.err_pct_p50` | 0.2053 |
| `house3.hold_across_flagged_cap_120s.full_coverage.err_pct_p95` | 1.223 |
| `house3.hold_across_flagged_cap_120s.full_coverage.err_pct_p99` | 2.997 |
| `house3.hold_across_flagged_cap_120s.low_coverage.days` | 147 |
| `house3.hold_across_flagged_cap_120s.low_coverage.days_over_gate` | 76 |
| `house3.hold_across_flagged_cap_120s.low_coverage.err_pct_max` | 11.93 |
| `house3.hold_across_flagged_cap_120s.low_coverage.err_pct_p50` | 1.029 |
| `house3.hold_across_flagged_cap_120s.low_coverage.err_pct_p95` | 6.938 |
| `house3.hold_across_flagged_cap_120s.low_coverage.err_pct_p99` | 11.38 |
| `house3.hold_across_flagged_cap_120s.view_days_without_exact` |  |

### energy_vs_exact_post_compress

| key | value |
|---|---|
| `house1.covered_minutes_mismatch_days` | 0 |
| `house1.days_in_exact` | 580 |
| `house1.days_in_view` | 580 |
| `house1.exact_days_without_view` |  |
| `house1.exact_days_without_view_count` | 0 |
| `house1.full_coverage.days` | 512 |
| `house1.full_coverage.days_over_gate` | 129 |
| `house1.full_coverage.days_view_higher` | 482 |
| `house1.full_coverage.days_view_lower` | 30 |
| `house1.full_coverage.err_pct_max` | 53.81 |
| `house1.full_coverage.err_pct_p50` | 0.4637 |
| `house1.full_coverage.err_pct_p95` | 2.435 |
| `house1.full_coverage.err_pct_p99` | 4.315 |
| `house1.full_coverage.signed_err_pct_mean` | 0.8399 |
| `house1.full_coverage.signed_err_pct_p50` | 0.4637 |
| `house1.low_coverage.days` | 68 |
| `house1.low_coverage.days_over_gate` | 31 |
| `house1.low_coverage.days_view_higher` | 64 |
| `house1.low_coverage.days_view_lower` | 4 |
| `house1.low_coverage.err_pct_max` | 48.32 |
| `house1.low_coverage.err_pct_p50` | 0.9274 |
| `house1.low_coverage.err_pct_p95` | 5.566 |
| `house1.low_coverage.err_pct_p99` | 22.59 |
| `house1.low_coverage.signed_err_pct_mean` | 1.972 |
| `house1.low_coverage.signed_err_pct_p50` | 0.9274 |
| `house1.median_cadence_s` | 7 |
| `house1.view_days_without_exact` |  |
| `house2.covered_minutes_mismatch_days` | 0 |
| `house2.days_in_exact` | 492 |
| `house2.days_in_view` | 492 |
| `house2.exact_days_without_view` |  |
| `house2.exact_days_without_view_count` | 0 |
| `house2.full_coverage.days` | 432 |
| `house2.full_coverage.days_over_gate` | 152 |
| `house2.full_coverage.days_view_higher` | 423 |
| `house2.full_coverage.days_view_lower` | 9 |
| `house2.full_coverage.err_pct_max` | 45.46 |
| `house2.full_coverage.err_pct_p50` | 0.6858 |
| `house2.full_coverage.err_pct_p95` | 1.947 |
| `house2.full_coverage.err_pct_p99` | 2.304 |
| `house2.full_coverage.signed_err_pct_mean` | 0.9203 |
| `house2.full_coverage.signed_err_pct_p50` | 0.6858 |
| `house2.low_coverage.days` | 60 |
| `house2.low_coverage.days_over_gate` | 30 |
| `house2.low_coverage.days_view_higher` | 60 |
| `house2.low_coverage.days_view_lower` | 0 |
| `house2.low_coverage.err_pct_max` | 12.11 |
| `house2.low_coverage.err_pct_p50` | 0.9746 |
| `house2.low_coverage.err_pct_p95` | 7.48 |
| `house2.low_coverage.err_pct_p99` | 10.07 |
| `house2.low_coverage.signed_err_pct_mean` | 2.078 |
| `house2.low_coverage.signed_err_pct_p50` | 0.9746 |
| `house2.median_cadence_s` | 7 |
| `house2.view_days_without_exact` |  |
| `house3.covered_minutes_mismatch_days` | 0 |
| `house3.days_in_exact` | 562 |
| `house3.days_in_view` | 562 |
| `house3.exact_days_without_view` |  |
| `house3.exact_days_without_view_count` | 0 |
| `house3.full_coverage.days` | 415 |
| `house3.full_coverage.days_over_gate` | 226 |
| `house3.full_coverage.days_view_higher` | 408 |
| `house3.full_coverage.days_view_lower` | 7 |
| `house3.full_coverage.err_pct_max` | 54.2 |
| `house3.full_coverage.err_pct_p50` | 1.17 |
| `house3.full_coverage.err_pct_p95` | 5.352 |
| `house3.full_coverage.err_pct_p99` | 10.23 |
| `house3.full_coverage.signed_err_pct_mean` | 1.831 |
| `house3.full_coverage.signed_err_pct_p50` | 1.17 |
| `house3.low_coverage.days` | 147 |
| `house3.low_coverage.days_over_gate` | 116 |
| `house3.low_coverage.days_view_higher` | 145 |
| `house3.low_coverage.days_view_lower` | 2 |
| `house3.low_coverage.err_pct_max` | 39.28 |
| `house3.low_coverage.err_pct_p50` | 2.648 |
| `house3.low_coverage.err_pct_p95` | 11.61 |
| `house3.low_coverage.err_pct_p99` | 29.35 |
| `house3.low_coverage.signed_err_pct_mean` | 4.328 |
| `house3.low_coverage.signed_err_pct_p50` | 2.648 |
| `house3.median_cadence_s` | 7 |
| `house3.view_days_without_exact` |  |

### energy_vs_exact_pre_compress

| key | value |
|---|---|
| `house1.covered_minutes_mismatch_days` | 0 |
| `house1.days_in_exact` | 580 |
| `house1.days_in_view` | 580 |
| `house1.full_coverage.days` | 512 |
| `house1.full_coverage.days_over_gate` | 129 |
| `house1.full_coverage.err_pct_max` | 53.81 |
| `house1.full_coverage.err_pct_p50` | 0.4637 |
| `house1.full_coverage.err_pct_p95` | 2.435 |
| `house1.full_coverage.err_pct_p99` | 4.315 |
| `house1.low_coverage.days` | 68 |
| `house1.low_coverage.days_over_gate` | 31 |
| `house1.low_coverage.err_pct_max` | 48.32 |
| `house1.low_coverage.err_pct_p50` | 0.9274 |
| `house1.low_coverage.err_pct_p95` | 5.566 |
| `house1.low_coverage.err_pct_p99` | 22.59 |
| `house1.median_cadence_s` | 7 |
| `house1.view_days_without_exact` |  |
| `house2.covered_minutes_mismatch_days` | 0 |
| `house2.days_in_exact` | 492 |
| `house2.days_in_view` | 492 |
| `house2.full_coverage.days` | 432 |
| `house2.full_coverage.days_over_gate` | 152 |
| `house2.full_coverage.err_pct_max` | 45.46 |
| `house2.full_coverage.err_pct_p50` | 0.6858 |
| `house2.full_coverage.err_pct_p95` | 1.947 |
| `house2.full_coverage.err_pct_p99` | 2.304 |
| `house2.low_coverage.days` | 60 |
| `house2.low_coverage.days_over_gate` | 30 |
| `house2.low_coverage.err_pct_max` | 12.11 |
| `house2.low_coverage.err_pct_p50` | 0.9746 |
| `house2.low_coverage.err_pct_p95` | 7.48 |
| `house2.low_coverage.err_pct_p99` | 10.07 |
| `house2.median_cadence_s` | 7 |
| `house2.view_days_without_exact` |  |
| `house3.covered_minutes_mismatch_days` | 0 |
| `house3.days_in_exact` | 562 |
| `house3.days_in_view` | 562 |
| `house3.full_coverage.days` | 415 |
| `house3.full_coverage.days_over_gate` | 226 |
| `house3.full_coverage.err_pct_max` | 54.2 |
| `house3.full_coverage.err_pct_p50` | 1.17 |
| `house3.full_coverage.err_pct_p95` | 5.352 |
| `house3.full_coverage.err_pct_p99` | 10.23 |
| `house3.low_coverage.days` | 147 |
| `house3.low_coverage.days_over_gate` | 116 |
| `house3.low_coverage.err_pct_max` | 39.28 |
| `house3.low_coverage.err_pct_p50` | 2.648 |
| `house3.low_coverage.err_pct_p95` | 11.61 |
| `house3.low_coverage.err_pct_p99` | 29.35 |
| `house3.median_cadence_s` | 7 |
| `house3.view_days_without_exact` |  |

### env

| key | value |
|---|---|
| `cpus` | 16 |
| `docker_vm_disk_bytes.free` | 964,172,861,440 |
| `docker_vm_disk_bytes.total` | 1,081,101,176,832 |
| `memory_mb_visible` | 15,583 |
| `postgres.checkpoint_timeout` | 15min |
| `postgres.effective_cache_size` | 8GB |
| `postgres.fsync` | on |
| `postgres.maintenance_work_mem` | 1947MB |
| `postgres.max_connections` | 100 |
| `postgres.max_wal_size` | 16GB |
| `postgres.shared_buffers` | 3GB |
| `postgres.synchronous_commit` | on |
| `postgres.timescaledb` | 2.31.0 |
| `postgres.version` | 17.11 |
| `postgres.wal_compression` | off |
| `postgres.work_mem` | 7791kB |
| `recorded_at` | 2026-11-01T18:23:16.784454+00:00 |

### estimates

| key | value |
|---|---|
| `duration_seconds` | 866.5 |
| `per_house.house1` | 62,640,072 |
| `per_house.house2` | 51,601,734 |
| `per_house.house3` | 62,951,346 |
| `rows_inserted` | 177,193,152 |
| `series_created` | 27 |

### extrapolation

| key | value |
|---|---|
| `assumptions` | the spec states no sampling rate; three scenarios are shown, REFIT: 10 series at about 7 s median cadence (measured), the 1 m aggregate has one row per series per minute that holds a sample; the scenarios assume every minute is covered (upper bound), 1h/1d aggregate bytes are scaled from the measured 3-house size by series/10, compressed raw size uses the measured 17x for all cadences (not measured for others), raw retention 13 months is NOT applied; figures are per year of ingest |
| `measured_inputs.agg_1m_bytes_per_row_uncompressed` | 151.3 |
| `measured_inputs.agg_1m_compression_ratio_scratch_measurement` | 19.14 |
| `measured_inputs.device_estimate_bytes_per_row` | 5.621 |
| `measured_inputs.raw_bytes_per_reading_compressed` | 5.617 |
| `scenario_main_meter_only_1hz.agg_1h_1d_gb_per_home_year` | 0.00127 |
| `scenario_main_meter_only_1hz.agg_1m_compressed_gb_per_home_year` | 0.0042 |
| `scenario_main_meter_only_1hz.agg_1m_uncompressed_gb_per_home_year` | 0.0795 |
| `scenario_main_meter_only_1hz.assumption` | 1 series per home, one reading per 1 s each |
| `scenario_main_meter_only_1hz.daily_ingest_rows_10k_homes` | 864,000,000 |
| `scenario_main_meter_only_1hz.device_estimate_gb_per_home_year` | 0 |
| `scenario_main_meter_only_1hz.measured_single_stream_rows_per_second` | 49,583 |
| `scenario_main_meter_only_1hz.raw_gb_per_home_year` | 0.1771 |
| `scenario_main_meter_only_1hz.readings_per_home_day` | 86,400 |
| `scenario_main_meter_only_1hz.required_avg_rows_per_second` | 10,000 |
| `scenario_main_meter_only_1hz.streams_needed_at_measured_rate` | 0.2 |
| `scenario_main_meter_only_1hz.tb_per_year_10k_homes_1m_compressed` | 1.83 |
| `scenario_main_meter_only_1hz.tb_per_year_10k_homes_1m_uncompressed` | 2.58 |
| `scenario_main_plus_9_devices_30s_with_estimates.agg_1h_1d_gb_per_home_year` | 0.01267 |
| `scenario_main_plus_9_devices_30s_with_estimates.agg_1m_compressed_gb_per_home_year` | 0.0416 |
| `scenario_main_plus_9_devices_30s_with_estimates.agg_1m_uncompressed_gb_per_home_year` | 0.7954 |
| `scenario_main_plus_9_devices_30s_with_estimates.assumption` | 10 series per home, one reading per 30 s each, 9 device_estimate series |
| `scenario_main_plus_9_devices_30s_with_estimates.daily_ingest_rows_10k_homes` | 288,000,000 |
| `scenario_main_plus_9_devices_30s_with_estimates.device_estimate_gb_per_home_year` | 0.0532 |
| `scenario_main_plus_9_devices_30s_with_estimates.measured_single_stream_rows_per_second` | 49,583 |
| `scenario_main_plus_9_devices_30s_with_estimates.raw_gb_per_home_year` | 0.059 |
| `scenario_main_plus_9_devices_30s_with_estimates.readings_per_home_day` | 28,800 |
| `scenario_main_plus_9_devices_30s_with_estimates.required_avg_rows_per_second` | 3,333 |
| `scenario_main_plus_9_devices_30s_with_estimates.streams_needed_at_measured_rate` | 0.07 |
| `scenario_main_plus_9_devices_30s_with_estimates.tb_per_year_10k_homes_1m_compressed` | 1.66 |
| `scenario_main_plus_9_devices_30s_with_estimates.tb_per_year_10k_homes_1m_uncompressed` | 9.2 |
| `scenario_refit_like_10_series_7s.agg_1h_1d_gb_per_home_year` | 0.01267 |
| `scenario_refit_like_10_series_7s.agg_1m_compressed_gb_per_home_year` | 0.0416 |
| `scenario_refit_like_10_series_7s.agg_1m_uncompressed_gb_per_home_year` | 0.7954 |
| `scenario_refit_like_10_series_7s.assumption` | 10 series per home, one reading per 7 s each |
| `scenario_refit_like_10_series_7s.daily_ingest_rows_10k_homes` | 1,234,285,714 |
| `scenario_refit_like_10_series_7s.device_estimate_gb_per_home_year` | 0 |
| `scenario_refit_like_10_series_7s.measured_single_stream_rows_per_second` | 49,583 |
| `scenario_refit_like_10_series_7s.raw_gb_per_home_year` | 0.2531 |
| `scenario_refit_like_10_series_7s.readings_per_home_day` | 123,429 |
| `scenario_refit_like_10_series_7s.required_avg_rows_per_second` | 14,286 |
| `scenario_refit_like_10_series_7s.streams_needed_at_measured_rate` | 0.29 |
| `scenario_refit_like_10_series_7s.tb_per_year_10k_homes_1m_compressed` | 3.07 |
| `scenario_refit_like_10_series_7s.tb_per_year_10k_homes_1m_uncompressed` | 10.61 |

### harness_check

| key | value |
|---|---|
| `backfill_keys_are_view_names` | True |
| `backfill_timed_view_keys` | energy.device_estimate_1d, energy.device_estimate_1h, energy.device_estimate_1m, energy.reading_1d, energy.reading_1h, energy.reading_1m |
| `compress_stats_reading.compressed_after_bytes` | 13,107,200 |
| `compress_stats_reading.compressed_before_bytes` | 193,036,288 |
| `compress_stats_reading.compressed_chunks` | 15 |
| `compress_stats_reading.ratio_compressed_chunks` | 14.73 |
| `compress_stats_reading.total_chunks` | 15 |
| `compressed_chunks_matches_db` | True |
| `csv_rows_loaded` | 200,000 |
| `db_compressed_chunks` | 15 |
| `ratio_is_number` | True |
| `scratch_db` | wattprint_audit_h |

### idempotency

| key | value |
|---|---|
| `post_compress.identical` | True |
| `post_compress.reading_1d_after.cov` | 22185510 |
| `post_compress.reading_1d_after.digest` | 5bc25fd96eca74f91323a3e9d63eee97 |
| `post_compress.reading_1d_after.n` | 16,340 |
| `post_compress.reading_1d_after.samples` | 191928740 |
| `post_compress.reading_1d_after.wh` | 27,346,573 |
| `post_compress.reading_1d_before.cov` | 22185510 |
| `post_compress.reading_1d_before.digest` | 5bc25fd96eca74f91323a3e9d63eee97 |
| `post_compress.reading_1d_before.n` | 16,340 |
| `post_compress.reading_1d_before.samples` | 191928740 |
| `post_compress.reading_1d_before.wh` | 27,346,573 |
| `post_compress.reading_rows_after` | 196,881,280 |
| `post_compress.reading_rows_before` | 196,881,280 |
| `post_compress.rows_bad` | 0 |
| `post_compress.rows_dup` | 1,000,000 |
| `post_compress.rows_in` | 1,000,000 |
| `post_compress.rows_new` | 0 |
| `pre_compress.identical` | True |
| `pre_compress.reading_1d_after.cov` | 22185510 |
| `pre_compress.reading_1d_after.digest` | a68ceee71176c9a989f1f1679f34f948 |
| `pre_compress.reading_1d_after.n` | 16,340 |
| `pre_compress.reading_1d_after.samples` | 191928740 |
| `pre_compress.reading_1d_after.wh` | 27,346,573 |
| `pre_compress.reading_1d_before.cov` | 22185510 |
| `pre_compress.reading_1d_before.digest` | a68ceee71176c9a989f1f1679f34f948 |
| `pre_compress.reading_1d_before.n` | 16,340 |
| `pre_compress.reading_1d_before.samples` | 191928740 |
| `pre_compress.reading_1d_before.wh` | 27,346,573 |
| `pre_compress.reading_rows_after` | 196,881,280 |
| `pre_compress.reading_rows_before` | 196,881,280 |
| `pre_compress.rows_bad` | 0 |
| `pre_compress.rows_dup` | 1,000,000 |
| `pre_compress.rows_in` | 1,000,000 |
| `pre_compress.rows_new` | 0 |

### isolation

| key | value |
|---|---|
| `audit_db.bad_tokens_checked` | 4 |
| `audit_db.device_estimate_1d_series_visible` | 9 |
| `audit_db.device_estimate_1h_series_visible` | 9 |
| `audit_db.device_estimate_1m_series_visible` | 9 |
| `audit_db.homes_checked` | 2 |
| `audit_db.own_reading_1d_rows_visible` | 5,800 |
| `audit_db.reading_1d_series_visible` | 10 |
| `audit_db.reading_1h_series_visible` | 10 |
| `audit_db.reading_1m_series_visible` | 10 |
| `audit_db.views_checked` | 15 |

### latency

| key | value |
|---|---|
| `cold_after_restart.compute_bill_month.first_call_ms` | 47.8 |
| `cold_after_restart.compute_bill_month.first_calls_ms` | 47.8, 21.3, 19, 18.6, 19.6 |
| `cold_after_restart.device_breakdown_1d_hourly.first_call_ms` | 17.6 |
| `cold_after_restart.device_breakdown_1d_hourly.first_calls_ms` | 17.6, 2.7, 2.1, 3, 2.7 |
| `cold_after_restart.device_breakdown_30d_daily.first_call_ms` | 6.3 |
| `cold_after_restart.device_breakdown_30d_daily.first_calls_ms` | 6.3, 2.9, 3.4, 3.1, 2.8 |
| `cold_after_restart.latest_power.first_call_ms` | 2.6 |
| `cold_after_restart.latest_power.first_calls_ms` | 2.6, 2.1, 1.8, 2, 2.2 |
| `cold_after_restart.series_1d_over_90d.first_call_ms` | 21 |
| `cold_after_restart.series_1d_over_90d.first_calls_ms` | 21, 3.7, 4.3, 3.7, 4 |
| `cold_after_restart.series_1h_over_45d.first_call_ms` | 5.9 |
| `cold_after_restart.series_1h_over_45d.first_calls_ms` | 5.9, 5.7, 5.4, 4.9, 5.3 |
| `cold_after_restart.series_5m_over_1d.first_call_ms` | 9.5 |
| `cold_after_restart.series_5m_over_1d.first_calls_ms` | 9.5, 7.7, 5.3, 5.9, 7.3 |
| `cold_after_restart.series_6h_over_90d.first_call_ms` | 17.1 |
| `cold_after_restart.series_6h_over_90d.first_calls_ms` | 17.1, 6.3, 6.2, 5.6, 6.6 |
| `lagging_watermark.latest_power.last_point` | LatestPower(ts=datetime.datetime(2026, 10, 31, 13, 27, tzinfo=datetime.timezone.utc), watts=1234.0) |
| `lagging_watermark.latest_power.target_p95_ms` | 20 |
| `lagging_watermark.latest_power.warm.max_ms` | 1.95 |
| `lagging_watermark.latest_power.warm.n` | 30 |
| `lagging_watermark.latest_power.warm.p50_ms` | 1.59 |
| `lagging_watermark.latest_power.warm.p95_ms` | 1.91 |
| `lagging_watermark.latest_power_sees_tail` | True |
| `lagging_watermark.raw_rows_restored` | True |
| `lagging_watermark.series_1d_over_90d.last_point` | Point(ts=datetime.datetime(2026, 10, 30, 17, 0, tzinfo=datetime.timezone.utc), avg_w=281.833300336567, min_w=155.0, max_w=10765.0, energy_wh=5298.452764550266) |
| `lagging_watermark.series_1d_over_90d.target_p95_ms` | 100 |
| `lagging_watermark.series_1d_over_90d.warm.max_ms` | 4.44 |
| `lagging_watermark.series_1d_over_90d.warm.n` | 30 |
| `lagging_watermark.series_1d_over_90d.warm.p50_ms` | 3.67 |
| `lagging_watermark.series_1d_over_90d.warm.p95_ms` | 4.41 |
| `lagging_watermark.series_1h_over_45d.last_point` | Point(ts=datetime.datetime(2026, 10, 31, 13, 0, tzinfo=datetime.timezone.utc), avg_w=1234.0, min_w=1234.0, max_w=1234.0, energy_wh=575.8666666666668) |
| `lagging_watermark.series_1h_over_45d.target_p95_ms` | 100 |
| `lagging_watermark.series_1h_over_45d.warm.max_ms` | 5.09 |
| `lagging_watermark.series_1h_over_45d.warm.n` | 30 |
| `lagging_watermark.series_1h_over_45d.warm.p50_ms` | 4.6 |
| `lagging_watermark.series_1h_over_45d.warm.p95_ms` | 5.08 |
| `lagging_watermark.series_5m_over_1d.last_point` | Point(ts=datetime.datetime(2026, 10, 31, 13, 25, tzinfo=datetime.timezone.utc), avg_w=1234.0, min_w=1234.0, max_w=1234.0, energy_wh=61.7) |
| `lagging_watermark.series_5m_over_1d.target_p95_ms` | 100 |
| `lagging_watermark.series_5m_over_1d.warm.max_ms` | 4.95 |
| `lagging_watermark.series_5m_over_1d.warm.n` | 30 |
| `lagging_watermark.series_5m_over_1d.warm.p50_ms` | 4.04 |
| `lagging_watermark.series_5m_over_1d.warm.p95_ms` | 4.79 |
| `lagging_watermark.tail_rows` | 772 |
| `lagging_watermark.tail_rows_end` | 2026-10-31T13:27:30+00:00 |
| `lagging_watermark.tail_rows_start` | 2026-10-31T11:57:30+00:00 |
| `lagging_watermark.watermarks.1d` | 2026-10-31T17:00:00+00:00 |
| `lagging_watermark.watermarks.1h` | 2026-10-31T12:00:00+00:00 |
| `lagging_watermark.watermarks.1m` | 2026-10-31T11:57:00+00:00 |
| `settled_data.compressed_chunks_reading` | 636 |
| `settled_data.compute_bill_month.pass` | True |
| `settled_data.compute_bill_month.target_p95_ms` | 100 |
| `settled_data.compute_bill_month.varied_windows.max_ms` | 18.39 |
| `settled_data.compute_bill_month.varied_windows.n` | 30 |
| `settled_data.compute_bill_month.varied_windows.p50_ms` | 15.81 |
| `settled_data.compute_bill_month.varied_windows.p95_ms` | 17.78 |
| `settled_data.compute_bill_month.warm.max_ms` | 31.24 |
| `settled_data.compute_bill_month.warm.n` | 30 |
| `settled_data.compute_bill_month.warm.p50_ms` | 15.65 |
| `settled_data.compute_bill_month.warm.p95_ms` | 17.49 |
| `settled_data.device_breakdown_1d_hourly.pass` | True |
| `settled_data.device_breakdown_1d_hourly.target_p95_ms` | 100 |
| `settled_data.device_breakdown_1d_hourly.varied_windows.max_ms` | 3.29 |
| `settled_data.device_breakdown_1d_hourly.varied_windows.n` | 30 |
| `settled_data.device_breakdown_1d_hourly.varied_windows.p50_ms` | 2.65 |
| `settled_data.device_breakdown_1d_hourly.varied_windows.p95_ms` | 3.21 |
| `settled_data.device_breakdown_1d_hourly.warm.max_ms` | 25.62 |
| `settled_data.device_breakdown_1d_hourly.warm.n` | 30 |
| `settled_data.device_breakdown_1d_hourly.warm.p50_ms` | 2.35 |
| `settled_data.device_breakdown_1d_hourly.warm.p95_ms` | 2.88 |
| `settled_data.device_breakdown_30d_daily.pass` | True |
| `settled_data.device_breakdown_30d_daily.target_p95_ms` | 100 |
| `settled_data.device_breakdown_30d_daily.varied_windows.max_ms` | 3.93 |
| `settled_data.device_breakdown_30d_daily.varied_windows.n` | 30 |
| `settled_data.device_breakdown_30d_daily.varied_windows.p50_ms` | 3.02 |
| `settled_data.device_breakdown_30d_daily.varied_windows.p95_ms` | 3.54 |
| `settled_data.device_breakdown_30d_daily.warm.max_ms` | 25.79 |
| `settled_data.device_breakdown_30d_daily.warm.n` | 30 |
| `settled_data.device_breakdown_30d_daily.warm.p50_ms` | 3.57 |
| `settled_data.device_breakdown_30d_daily.warm.p95_ms` | 4.23 |
| `settled_data.latest_power.pass` | True |
| `settled_data.latest_power.target_p95_ms` | 20 |
| `settled_data.latest_power.varied_windows.max_ms` | 5.83 |
| `settled_data.latest_power.varied_windows.n` | 30 |
| `settled_data.latest_power.varied_windows.p50_ms` | 1.5 |
| `settled_data.latest_power.varied_windows.p95_ms` | 3.48 |
| `settled_data.latest_power.warm.max_ms` | 6.33 |
| `settled_data.latest_power.warm.n` | 30 |
| `settled_data.latest_power.warm.p50_ms` | 1.55 |
| `settled_data.latest_power.warm.p95_ms` | 2.35 |
| `settled_data.runs_per_case` | 30 |
| `settled_data.series_1d_over_90d.pass` | True |
| `settled_data.series_1d_over_90d.target_p95_ms` | 100 |
| `settled_data.series_1d_over_90d.varied_windows.max_ms` | 4.07 |
| `settled_data.series_1d_over_90d.varied_windows.n` | 30 |
| `settled_data.series_1d_over_90d.varied_windows.p50_ms` | 3.25 |
| `settled_data.series_1d_over_90d.varied_windows.p95_ms` | 3.73 |
| `settled_data.series_1d_over_90d.warm.max_ms` | 25.11 |
| `settled_data.series_1d_over_90d.warm.n` | 30 |
| `settled_data.series_1d_over_90d.warm.p50_ms` | 3.5 |
| `settled_data.series_1d_over_90d.warm.p95_ms` | 4.54 |
| `settled_data.series_1h_over_45d.pass` | True |
| `settled_data.series_1h_over_45d.target_p95_ms` | 100 |
| `settled_data.series_1h_over_45d.varied_windows.max_ms` | 5.56 |
| `settled_data.series_1h_over_45d.varied_windows.n` | 30 |
| `settled_data.series_1h_over_45d.varied_windows.p50_ms` | 4.72 |
| `settled_data.series_1h_over_45d.varied_windows.p95_ms` | 5.04 |
| `settled_data.series_1h_over_45d.warm.max_ms` | 8.12 |
| `settled_data.series_1h_over_45d.warm.n` | 30 |
| `settled_data.series_1h_over_45d.warm.p50_ms` | 4.61 |
| `settled_data.series_1h_over_45d.warm.p95_ms` | 5.96 |
| `settled_data.series_5m_over_1d.pass` | True |
| `settled_data.series_5m_over_1d.target_p95_ms` | 100 |
| `settled_data.series_5m_over_1d.varied_windows.max_ms` | 5.86 |
| `settled_data.series_5m_over_1d.varied_windows.n` | 30 |
| `settled_data.series_5m_over_1d.varied_windows.p50_ms` | 4.7 |
| `settled_data.series_5m_over_1d.varied_windows.p95_ms` | 5.6 |
| `settled_data.series_5m_over_1d.warm.max_ms` | 29.76 |
| `settled_data.series_5m_over_1d.warm.n` | 30 |
| `settled_data.series_5m_over_1d.warm.p50_ms` | 3.59 |
| `settled_data.series_5m_over_1d.warm.p95_ms` | 4.91 |
| `settled_data.series_6h_over_90d.pass` | True |
| `settled_data.series_6h_over_90d.target_p95_ms` | 100 |
| `settled_data.series_6h_over_90d.varied_windows.max_ms` | 5.05 |
| `settled_data.series_6h_over_90d.varied_windows.n` | 30 |
| `settled_data.series_6h_over_90d.varied_windows.p50_ms` | 4.19 |
| `settled_data.series_6h_over_90d.varied_windows.p95_ms` | 4.95 |
| `settled_data.series_6h_over_90d.warm.max_ms` | 27.04 |
| `settled_data.series_6h_over_90d.warm.n` | 30 |
| `settled_data.series_6h_over_90d.warm.p50_ms` | 4.16 |
| `settled_data.series_6h_over_90d.warm.p95_ms` | 5.3 |

### load

| key | value |
|---|---|
| `house1.csv_rows` | 6,960,008 |
| `house1.load_seconds` | 1,404 |
| `house1.process_wall_seconds` | 1,405 |
| `house1.readings_per_s` | 49,583 |
| `house1.rows_bad` | 0 |
| `house1.rows_dup` | 0 |
| `house1.rows_in` | 69,600,080 |
| `house1.rows_new` | 69,600,080 |
| `house1.shift_days` | 4,131 |
| `house2.csv_rows` | 5,733,526 |
| `house2.load_seconds` | 1,281 |
| `house2.process_wall_seconds` | 1,282 |
| `house2.readings_per_s` | 44,769 |
| `house2.rows_bad` | 0 |
| `house2.rows_dup` | 0 |
| `house2.rows_in` | 57,335,260 |
| `house2.rows_new` | 57,335,260 |
| `house2.shift_days` | 4,174 |
| `house3.csv_rows` | 6,994,594 |
| `house3.load_seconds` | 1,568 |
| `house3.process_wall_seconds` | 1,569 |
| `house3.readings_per_s` | 44,623 |
| `house3.rows_bad` | 0 |
| `house3.rows_dup` | 0 |
| `house3.rows_in` | 69,945,940 |
| `house3.rows_new` | 69,945,940 |
| `house3.shift_days` | 4,169 |
| `run_parallel_2-3.aggregate_readings_per_s` | 81,141 |
| `run_parallel_2-3.houses` | 2, 3 |
| `run_parallel_2-3.mean_per_stream_readings_per_s` | 44,696 |
| `run_parallel_2-3.mode` | parallel |
| `run_parallel_2-3.readings` | 127,281,200 |
| `run_parallel_2-3.wall_seconds` | 1,569 |
| `run_sequential_1.aggregate_readings_per_s` | 49,547 |
| `run_sequential_1.houses` | 1 |
| `run_sequential_1.mean_per_stream_readings_per_s` | 49,583 |
| `run_sequential_1.mode` | sequential |
| `run_sequential_1.readings` | 69,600,080 |
| `run_sequential_1.wall_seconds` | 1,405 |

### policies

| key | value |
|---|---|
| `jobs_remaining` | 0 |
| `state` | off |

### policy_drill

| key | value |
|---|---|
| `aggregate_rows_before_policies.1d` | 130 |
| `aggregate_rows_before_policies.1h` | 2,760 |
| `aggregate_rows_before_policies.1m` | 164,310 |
| `copied_rows.reading` | 1,533,860 |
| `jobs_paused_for_deterministic_drill` | True |
| `mid_slice_raw_rows_intact` | True |
| `old_slice.materialized_rows_after_1m_retention_job.1d` | 50 |
| `old_slice.materialized_rows_after_1m_retention_job.1h` | 1,200 |
| `old_slice.materialized_rows_after_1m_retention_job.1m` | 0 |
| `old_slice.materialized_rows_after_backfill_over_dropped_range.1d` | 0 |
| `old_slice.materialized_rows_after_backfill_over_dropped_range.1h` | 0 |
| `old_slice.materialized_rows_after_backfill_over_dropped_range.1m` | 0 |
| `old_slice.materialized_rows_after_raw_retention.1d` | 50 |
| `old_slice.materialized_rows_after_raw_retention.1h` | 1,200 |
| `old_slice.materialized_rows_after_raw_retention.1m` | 71,280 |
| `old_slice.materialized_rows_after_refresh_policies.1d` | 50 |
| `old_slice.materialized_rows_after_refresh_policies.1h` | 1,200 |
| `old_slice.materialized_rows_after_refresh_policies.1m` | 71,280 |
| `old_slice.materialized_rows_before.1d` | 50 |
| `old_slice.materialized_rows_before.1h` | 1,200 |
| `old_slice.materialized_rows_before.1m` | 71,280 |
| `old_slice.raw_rows_after` | 0 |
| `old_slice.raw_rows_before` | 700,920 |
| `old_slice.view_rows_after_1m_retention_job.1d` | 50 |
| `old_slice.view_rows_after_1m_retention_job.1h` | 1,200 |
| `old_slice.view_rows_after_1m_retention_job.1m` | 0 |
| `old_slice.view_rows_after_backfill_over_dropped_range.1d` | 0 |
| `old_slice.view_rows_after_backfill_over_dropped_range.1h` | 0 |
| `old_slice.view_rows_after_backfill_over_dropped_range.1m` | 0 |
| `old_slice.view_rows_after_raw_retention.1d` | 50 |
| `old_slice.view_rows_after_raw_retention.1h` | 1,200 |
| `old_slice.view_rows_after_raw_retention.1m` | 71,280 |
| `old_slice.view_rows_after_refresh_policies.1d` | 50 |
| `old_slice.view_rows_after_refresh_policies.1h` | 1,200 |
| `old_slice.view_rows_after_refresh_policies.1m` | 71,280 |
| `old_slice.view_rows_before.1d` | 50 |
| `old_slice.view_rows_before.1h` | 1,200 |
| `old_slice.view_rows_before.1m` | 71,280 |
| `raw_chunks_after_compression_policy.compressed` | 10 |
| `raw_chunks_after_compression_policy.total` | 12 |
| `raw_chunks_after_raw_retention.compressed` | 5 |
| `raw_chunks_after_raw_retention.total` | 7 |
| `raw_chunks_before.compressed` | 0 |
| `raw_chunks_before.total` | 12 |
| `recent_slice_raw_rows_intact` | True |
| `refresh_policy_jobs_found.1d` | True |
| `refresh_policy_jobs_found.1h` | True |
| `refresh_policy_jobs_found.1m` | True |
| `retention_policy_jobs` | device_estimate, device_estimate_1m, reading, reading_1m |
| `run_at` | 2026-11-01T18:19:40.514269+00:00 |
| `slices.mid` | 2026-09-01 00:00:00+00:00, 2026-09-04 00:00:00+00:00 |
| `slices.old` | 2025-02-01 00:00:00+00:00, 2025-02-06 00:00:00+00:00 |
| `slices.recent` | 2026-10-25 00:00:00+00:00, 2026-11-01 00:00:00+00:00 |

### rebuild

| key | value |
|---|---|
| `from_empty.device_types_seeded` | 22 |
| `from_empty.load_output` | house 1: rows_in=100000 rows_new=100000 rows_dup=0 rows_bad=0 in 1.8s (55,486 readings/s) |
| `from_empty.manual_steps` | 0 |
| `from_empty.policy_jobs_after_migration` | 12 |
| `from_empty.readings` | 100,000 |
| `from_empty.series` | 10 |
| `from_empty.tariff_tiers_seeded` | 11 |

### refresh_cost

| key | value |
|---|---|
| `forced_30_day_window_seconds.1d` | 0.089 |
| `forced_30_day_window_seconds.1h` | 1.218 |
| `forced_30_day_window_seconds.1m` | 31.16 |
| `one_invalidated_day_refresh_seconds.1d` | 0.016 |
| `one_invalidated_day_refresh_seconds.1h` | 0.013 |
| `one_invalidated_day_refresh_seconds.1m` | 0.015 |
| `policy_window_nothing_to_do_seconds.1d` | 0.004 |
| `policy_window_nothing_to_do_seconds.1h` | 0.004 |
| `policy_window_nothing_to_do_seconds.1m` | 0.004 |
| `policy_window_with_one_invalidation_seconds.1d` | 0.014 |
| `policy_window_with_one_invalidation_seconds.1h` | 0.009 |
| `policy_window_with_one_invalidation_seconds.1m` | 0.009 |
| `reading_1d_checksum_after_forced_recompute_equals_before` | True |
| `reading_1d_checksum_restored_after_marker_cycle` | True |
| `reading_1d_diff_vs_snapshot_after_forced_recompute.max_rel_diff` | 0 |
| `reading_1d_diff_vs_snapshot_after_forced_recompute.new_rows` | 0 |
| `reading_1d_diff_vs_snapshot_after_forced_recompute.rows_changed` | 0 |
| `reading_1d_diff_vs_snapshot_after_forced_recompute.rows_lost` | 0 |
| `reading_1d_diff_vs_snapshot_after_forced_recompute.rows_now` | 16,340 |
| `reading_1d_diff_vs_snapshot_after_marker_cycle.max_rel_diff` | 0 |
| `reading_1d_diff_vs_snapshot_after_marker_cycle.new_rows` | 0 |
| `reading_1d_diff_vs_snapshot_after_marker_cycle.rows_changed` | 0 |
| `reading_1d_diff_vs_snapshot_after_marker_cycle.rows_lost` | 0 |
| `reading_1d_diff_vs_snapshot_after_marker_cycle.rows_now` | 16,340 |
| `scratch_comparison.window_only.backfill_seconds_per_view.energy.device_estimate_1d` | 0.01 |
| `scratch_comparison.window_only.backfill_seconds_per_view.energy.device_estimate_1h` | 0.01 |
| `scratch_comparison.window_only.backfill_seconds_per_view.energy.device_estimate_1m` | 0.01 |
| `scratch_comparison.window_only.backfill_seconds_per_view.energy.reading_1d` | 0.07 |
| `scratch_comparison.window_only.backfill_seconds_per_view.energy.reading_1h` | 0.65 |
| `scratch_comparison.window_only.backfill_seconds_per_view.energy.reading_1m` | 21.69 |
| `scratch_comparison.window_only.copied_rows.reading` | 3,850,040 |
| `scratch_comparison.window_plus_newer_raw_with_1m_and_1h_materialized_only.backfill_seconds_per_view.energy.device_estimate_1d` | 0.01 |
| `scratch_comparison.window_plus_newer_raw_with_1m_and_1h_materialized_only.backfill_seconds_per_view.energy.device_estimate_1h` | 0.01 |
| `scratch_comparison.window_plus_newer_raw_with_1m_and_1h_materialized_only.backfill_seconds_per_view.energy.device_estimate_1m` | 0.01 |
| `scratch_comparison.window_plus_newer_raw_with_1m_and_1h_materialized_only.backfill_seconds_per_view.energy.reading_1d` | 0.04 |
| `scratch_comparison.window_plus_newer_raw_with_1m_and_1h_materialized_only.backfill_seconds_per_view.energy.reading_1h` | 0.56 |
| `scratch_comparison.window_plus_newer_raw_with_1m_and_1h_materialized_only.backfill_seconds_per_view.energy.reading_1m` | 22.29 |
| `scratch_comparison.window_plus_newer_raw_with_1m_and_1h_materialized_only.copied_rows.reading` | 16,882,370 |
| `scratch_comparison.window_plus_newer_unmaterialized_raw.backfill_seconds_per_view.energy.device_estimate_1d` | 0.01 |
| `scratch_comparison.window_plus_newer_unmaterialized_raw.backfill_seconds_per_view.energy.device_estimate_1h` | 0.01 |
| `scratch_comparison.window_plus_newer_unmaterialized_raw.backfill_seconds_per_view.energy.device_estimate_1m` | 0.01 |
| `scratch_comparison.window_plus_newer_unmaterialized_raw.backfill_seconds_per_view.energy.reading_1d` | 6.48 |
| `scratch_comparison.window_plus_newer_unmaterialized_raw.backfill_seconds_per_view.energy.reading_1h` | 0.67 |
| `scratch_comparison.window_plus_newer_unmaterialized_raw.backfill_seconds_per_view.energy.reading_1m` | 22.14 |
| `scratch_comparison.window_plus_newer_unmaterialized_raw.copied_rows.reading` | 16,882,370 |

### stats

| key | value |
|---|---|
| `bytes.aggregates.device_estimate_1d` | 5,480,448 |
| `bytes.aggregates.device_estimate_1h` | 52,707,328 |
| `bytes.aggregates.device_estimate_1m` | 3,009,716,224 |
| `bytes.aggregates.reading_1d` | 6,168,576 |
| `bytes.aggregates.reading_1h` | 58,744,832 |
| `bytes.aggregates.reading_1m` | 3,357,270,016 |
| `bytes.aggregates_total` | 6,490,087,424 |
| `bytes.device_estimate` | 995,926,016 |
| `bytes.reading` | 1,105,944,576 |
| `bytes_per_device_estimate_raw` | 5.621 |
| `bytes_per_home_year_reading_plus_aggregates` | 883,957,799 |
| `bytes_per_reading_incl_reading_aggregates` | 23 |
| `bytes_per_reading_raw` | 5.617 |
| `home_days_of_data.REFIT House 1` | 639 |
| `home_days_of_data.REFIT House 2` | 617.4 |
| `home_days_of_data.REFIT House 3` | 614.6 |
| `home_years` | 5.123 |
| `rows.aggregates.device_estimate_1d` | 14,706 |
| `rows.aggregates.device_estimate_1h` | 342,054 |
| `rows.aggregates.device_estimate_1m` | 20,325,051 |
| `rows.aggregates.reading_1d` | 16,340 |
| `rows.aggregates.reading_1h` | 378,670 |
| `rows.aggregates.reading_1m` | 22,185,510 |
| `rows.device_estimate` | 177,193,152 |
| `rows.reading` | 196,881,280 |
| `total_database_bytes` | 8,591,958,016 |

<!-- audit:end -->
