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
| `recorded_at` | 2026-11-01T15:13:55.519850+00:00 |
| `refit_csv_bytes.house1` | 400,840,083 |
| `refit_csv_bytes.house10` | 398,756,360 |
| `refit_csv_bytes.house11` | 255,832,544 |
| `refit_csv_bytes.house12` | 335,009,288 |
| `refit_csv_bytes.house13` | 276,518,579 |
| `refit_csv_bytes.house15` | 353,152,325 |
| `refit_csv_bytes.house16` | 333,937,465 |
| `refit_csv_bytes.house17` | 317,925,929 |
| `refit_csv_bytes.house18` | 301,534,016 |
| `refit_csv_bytes.house19` | 320,691,540 |
| `refit_csv_bytes.house2` | 325,391,201 |
| `refit_csv_bytes.house20` | 299,757,142 |
| `refit_csv_bytes.house21` | 316,713,466 |
| `refit_csv_bytes.house3` | 407,273,065 |
| `refit_csv_bytes.house4` | 395,763,806 |
| `refit_csv_bytes.house5` | 435,272,416 |
| `refit_csv_bytes.house6` | 366,398,284 |
| `refit_csv_bytes.house7` | 388,975,788 |
| `refit_csv_bytes.house8` | 355,439,146 |
| `refit_csv_bytes.house9` | 358,228,620 |

### estimates

| key | value |
|---|---|
| `duration_seconds` | 866.5 |
| `per_house.house1` | 62,640,072 |
| `per_house.house2` | 51,601,734 |
| `per_house.house3` | 62,951,346 |
| `rows_inserted` | 177,193,152 |
| `series_created` | 27 |

### idempotency

| key | value |
|---|---|
| `post_compress.identical` | True |
| `post_compress.reading_1d_after.cov` | 22185510 |
| `post_compress.reading_1d_after.digest` | a68ceee71176c9a989f1f1679f34f948 |
| `post_compress.reading_1d_after.n` | 16,340 |
| `post_compress.reading_1d_after.samples` | 191928740 |
| `post_compress.reading_1d_after.wh` | 27,346,573 |
| `post_compress.reading_1d_before.cov` | 22185510 |
| `post_compress.reading_1d_before.digest` | a68ceee71176c9a989f1f1679f34f948 |
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
