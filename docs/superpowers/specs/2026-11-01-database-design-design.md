# WattPrint Database Design: Spec

Date: 2026-11-01 · Status: draft for approval · Scope: schema, operating rules, ingest pipeline, audit/simulation. API and NILM model code are out of scope.

Legend: **[U]** decided by the user · **[C]** my call, change if you disagree · **[V]** verified by running it on 2026-11-01 · **[TBV]** must be verified during the build.

## 1. Intent

WattPrint needs one database that can hold a household from sign-up to bill: the account, the home, the meter, the raw power readings, the per-device estimates, tariffs and bills, anomalies, Copilot conversations and the knowledge base behind them. It must behave like a real product (Sense-like), and REFIT is only the first data source pushed through the production path, not a reason to cut corners.

The product screens we mirror (24 Sense screenshots in `docs/sense_app_imgs`, WattPrint adds modules 3 and 4 from the pitch deck):
- **Now**: latest power, always-on / other / per-device bubbles, today's cost, timeline of on/off cycles.
- **Meter**: power chart at Min / Hour / Day / Week / Month zoom.
- **Dashboard**: this month vs last month, compare with neighbours, goals (alerts).
- **Devices**: list, per-device detail (avg W while on, cost/yr, usage chart, timeline), rename / merge / delete / alert settings.
- **Settings**: My Home profile, electricity rate, billing cycle day, connected sources.

## 2. Goals, non-goals, anti-goals

Goals
- Ingest REFIT through the same path a real meter would use (idempotent, checkpointed, auditable).
- Every screen above is served from a pre-aggregated read model, never from a scan of raw data.
- Hard facts (kWh, VND, units, citations) come from SQL; the LLM only explains (deck, slide 3-4).
- Provable behaviour: an audit/simulation with REFIT must pass before the design is called done.

Non-goals
- No realtime waveform or sub-second live stream [U]. "Now" polls the API every few seconds and reads the DB.
- No raw waveform storage [C]: the device works at tens of kHz and sends only derived power.
- No Redis, no object storage, no separate vector DB at this stage [U]. Schema must not block adding them later.
- No boarding-house or business tariffs yet [C]; the tariff tables are shaped so they can be added.

Anti-goals (failure even if it "works")
- A design that only fits REFIT's quirks (UK homes, 9 fixed channels, 8 s cadence).
- Business numbers computed by an LLM or recomputed differently in two places.
- A schema that cannot be rebuilt from migrations on an empty volume.

## 3. Approaches considered

| | Stack | Verdict |
|---|---|---|
| **A** | One PostgreSQL 17 instance with TimescaleDB (time series) and pgvector (RAG) | **Chosen [U]** |
| B | InfluxDB for readings, PostgreSQL for the rest | Rejected: two systems, joins with billing/devices done in app code, Text-to-SQL harder |
| C | A + Redis live path + object storage cold tier | Rejected for now [U]: live view dropped; revisit when scale demands |

Why A fits: Text-to-SQL and billing need relational data next to the time series; the repo already runs Timescale; one thing to back up and secure. Reference: the sibling project `anno-bot-merge` runs the same pattern in production-like use (hypertable as write store, continuous aggregate as read model).

## 4. Verified facts and constraints [V]

- Image `timescale/timescaledb:latest-pg17` = PostgreSQL 17.11, TimescaleDB 2.31.0, pgvector 0.8.1, plus `unaccent`, `pg_trgm`, `btree_gin`, `pg_stat_statements`. `timescaledb_toolkit` is **not** present, so no `time_weight`. (An earlier claim that this image lacks pgvector was wrong.) Tag `2.31.0-pg17` exists: **pin it** instead of `latest`.
- In a transaction: `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous) ... WITH NO DATA` works; `WITH DATA` and `refresh_continuous_aggregate()` fail. Alembic's `autocommit_block()` runs the refresh correctly through SQLAlchemy 2.1.6 + asyncpg 0.32.0 + Alembic 1.20.1 (the versions in `uv.lock`).
- Continuous aggregate on a continuous aggregate (1 h over 1 m) works, including refresh policies and `materialized_only = false`.
- A hypertable with `PRIMARY KEY (series_id, ts)` compresses with `segmentby = series_id`; `ON CONFLICT DO NOTHING` and `DO UPDATE` both work on already-compressed chunks. Both `add_compression_policy()` (function) and `add_columnstore_policy()` (procedure) exist. Synthetic compression was ~14x; real ratio is a simulation output, not a promise.
- pgvector: `vector(1024)` and `halfvec(3072)` HNSW indexes build; `pgvector` 0.5.1 with SQLAlchemy typed columns, `cosine_distance` ordering and `op.create_index(..., postgresql_using="hnsw")` work over asyncpg.
- REFIT `Time` equals the `Unix` column in UTC (checked). 20 houses (no House 14), ~119 M rows, ~1.19 B points once each of the 10 channels is its own row. Sample gaps are irregular (1-15 s, 7 gaps over one hour in House 1's first 2 M rows); the `Issues` flag is set on ~1.8% of rows there. Appliance names change mid-recording in several houses (e.g. House 11, House 5).

## 5. Principles

1. UTC `timestamptz` everywhere; local time only at the edge. Daily buckets are cut in `Asia/Ho_Chi_Minh` [TBV with hierarchical continuous aggregates].
2. Money is `numeric`, never float. Power is `real` (W), derived energy is `double precision`.
3. Hypertable = write store; continuous aggregate = read model. Readers stop at the last closed bucket (pattern from anno-bot).
4. Hypertable keys are small integers (`series_id int`), relational tables use native `uuid`. Hypertables carry no secondary indexes beyond the primary key unless a measured query needs one.
5. Deterministic code decides numbers; the Copilot reads, it does not compute.
6. Every schema change is an Alembic revision, rebuildable on an empty volume. Timescale DDL lives in `op.execute`; refreshes and backfills run inside `autocommit_block()`.
7. Schemas by domain, least-privilege roles with explicit grants (never `ALL TABLES`).

## 6. Schemas and tables

Existing: `public.users`, `public.refresh_tokens`, `alembic_version` stay where they are. New domains get their own schema.

### 6.1 `core` (identity, home, hardware)

| Table | Key columns | Notes |
|---|---|---|
| `home` | `id uuid`, `name`, `postal_code`, `province_code`, `home_type`, `floor_area_m2`, `year_built`, `occupants`, `timezone` (default and, in this phase, CHECK-constrained to `Asia/Ho_Chi_Minh` [C]; the column exists so multi-timezone support is a constraint change plus a second `_1d` view, not a schema redesign), `tariff_plan_code`, `billing_cycle_day` (1-28) | Mirrors Sense "My Home" + "Electricity Info" |
| `home_member` | `home_id`, `user_id`, `role` (`owner`/`member`), `joined_at` | PK `(home_id, user_id)`, **UNIQUE `(user_id)`**: one account, one home [U]. Relaxing later is a drop of one constraint |
| `home_invite` | `id`, `home_id`, `code_hash`, `role`, `expires_at`, `used_by`, `used_at` | Members join with a code; only the hash is stored |
| `meter` | `id uuid`, `serial` unique, `home_id` null, `claim_code_hash`, `claimed_at`, `firmware`, `last_seen_at`, `status` | Device ships with a one-time pairing code; first claim binds it to a home [U] |
| `device` | `id uuid`, `home_id`, `device_type_code`, `name`, `room`, `origin` (`nilm`/`plug`/`manual`), `show_on_timeline`, `active_from`, `active_to`, `merged_into_id`, `deleted_at` | Rename / merge / delete as in Sense. A renamed physical channel (REFIT) becomes a new device with its own validity range |
| `device_alert_rule` | `device_id`, `kind` (`on`/`off`/`custom`), `params jsonb`, `enabled` | Sense "Manage" tab |

### 6.2 `catalog` (reference data, seeded)

- `metric(event_type pk, unit, aggregation)`: same idea as anno-bot's `sensor_metric` (`power_w` mean, `energy_wh` energy, later `reactive_power_var`, ...). `energy.series.metric` references it so names cannot drift.
- `device_type(code pk, label_vi, label_en, typical_watts, tip_text)`: feeds the "About fridges" card and Copilot hints.

### 6.3 `energy` (time series)

`series` is the only thing hypertables point at: one row per (home, channel, metric).

| Table | Columns | Notes |
|---|---|---|
| `series` | `series_id int identity pk`, `home_id`, `kind` (`main`/`plug`/`device`), `device_id` null, `meter_id` null, `source_channel` text null, `metric` → `catalog.metric`, `unit` | `main` = breaker-level meter, `plug` = measured appliance (REFIT appliance channels, Wemo/TP-Link style), `device` = NILM output. UNIQUE `(home_id, kind, device_id, metric)` **NULLS NOT DISTINCT**, so a home has exactly one `main` series per metric [C]. `(meter_id, source_channel)` is how the ingest path turns "meter X, channel `Appliance3`" into a `series_id`; replacing a meter re-points `meter_id`, the series and its history stay |
| `reading` (**hypertable**) | `ts`, `series_id`, `value real`, `quality smallint` | Measured data (`main`, `plug`). PK `(series_id, ts)`. `quality` bit flags: 1 = source flagged bad (REFIT `Issues`), 2 = gap-filled, 4 = clock-adjusted |
| `device_estimate` (**hypertable**) | `ts`, `series_id`, `value real`, `run_id int` | NILM output. PK `(series_id, ts)`, upsert, latest run wins. Re-running the model overwrites, no versions piling up |
| `inference_run` | `run_id`, `home_id`, `model_name`, `model_version`, `window_start`, `window_end`, `started_at`, `finished_at`, `status` | Audit of who produced which estimate |
| `weather_hourly` | `province_code`, `ts`, `temp_c`, `humidity_pct` | PK `(province_code, ts)`; small, plain table |

Continuous aggregates (read model), each with `avg_w, min_w, max_w, last_w, n` and an `energy_wh` column:
- `reading_1m` → `reading_1h` → `reading_1d` and `device_estimate_1m` → `_1h` → `_1d`.
- Real-time aggregation on; policies: refresh every minute for 1 m, hourly for 1 h, hourly for 1 d. `start_offset` for `_1m` must be at least the maximum expected ingest lag (anno-bot lesson).
- `energy_wh` rule [C]: in `_1m`, `avg_w × 60 / 3600` for a bucket that has at least one sample (zero-order hold inside the bucket). In `_1h` and `_1d`, the **sum of `energy_wh` of the child buckets that exist**, plus `covered_minutes`, so coverage = `covered_minutes / expected`. Missing time counts as 0 Wh and is never filled in; no mean of means. A bill whose coverage is below a threshold is flagged `partial` instead of silently under-billing. The audit reference and its tolerance are in section 9.
- Zoom ladder for the API (Min/Hour/Day/Week/Month in the app): pick the finest step from `1m, 5m, 15m, 30m, 1h, 3h, 6h, 1d` that keeps the series under `max_points` (anno-bot's rule); `Min`-level detail can come from raw `reading` for short windows.

### 6.4 `billing`

- `tariff_plan(code pk, name, currency)` and `tariff_version(id, plan_code, valid_from, valid_to, vat_rate, source_doc)`: homes point at a plan **code**; when EVN changes prices we add a dated version, no home is re-pointed [C]. Seeded with two versions of the Vietnamese residential tariff, which is exactly the case this design exists for: Decision 1279/QĐ-BCT (6 tiers, from 2025-05-10) and Decision 2892 (5 tiers, from 2026-11-01, supplied by the user and matching the Thanh Nien report of 2026-11-01). The deck's "6 bậc" is therefore out of date. The number of tiers is data, not schema.
- `tariff_tier(version_id, tier_no, from_kwh, to_kwh, price_per_kwh numeric)`: PK `(version_id, tier_no)`.
- `bill(id, home_id, period_start, period_end, version_id, kwh_total, amount_before_vat, vat_amount, amount_total, coverage, tariff_straddle, status` `open`/`partial`/`closed`, `computed_at)`: UNIQUE `(home_id, period_start)`; recomputed idempotently from `reading_1d` using `home.billing_cycle_day`. MVP applies the tiers of the version valid on `period_start` as-is [C]. A cycle that contains a version change (for example 15 Oct to 14 Nov across the 2026-11-01 switch) is billed with that version and flagged `tariff_straddle = true`. Proration of tier limits and splitting a bill at the price-change date are **not** built: neither the user's table nor the news report states the official rule, so it is not guessed and must be confirmed from the official text before it is implemented.
- `bill_item(bill_id, device_id null, label, kwh, share, amount)`: per-device cost is the device's **share of kWh applied to the total bill** [C] (deck example: 151.6 kWh = 42% of the home = 426,669 VND). `label` covers `always_on` and `other`.

Tier crossing and month-end forecast are computed by service code from `bill` + forecast, not stored as logic in the database.

### 6.5 `insight` (module 3: events, anomalies, forecast, comparison)

| Table | Notes |
|---|---|
| `device_cycle` | `device_id`, `start_ts`, `end_ts`, `energy_wh`, `peak_w`. The "AC was on for 13 minutes" timeline is built from this. Hypertable (30-day chunks) [C] |
| `alert` | `home_id`, `device_id` null, `kind` (`long_run`, `standby_waste`, `tier_near`, ...), `severity`, `ts`, `payload jsonb`, `status` |
| `forecast_snapshot` | `home_id`, `generated_at`, `horizon_date`, `kwh`, `amount`, `tier_cross_date`, `model_version` |
| `cohort_stat` | Compare-with-neighbours: per `(cohort_key, period)` percentiles and `n_homes`; **refuse to publish a cohort below a minimum size** (Sense shows "35 homes", minimum to be chosen) |

### 6.6 `copilot` (module 4)

- `conversation(id, home_id, user_id, created_at)` and `message(id, conversation_id, role, content, created_at)`.
- `tool_call(id, message_id, tool, input jsonb, sql_text, unit, duration_ms, ok)`: every number shown to the user can be traced to a query, unit and source, which is what the verifier step in the concept note needs.
- `suggestion(id, home_id, device_id null, alert_id null, kind, title, body, expected_kwh, expected_amount, status, created_at)` and `suggestion_feedback(suggestion_id, user_id, action, at, note)`: proactive loop with accept/ignore learning.
- `savings_measure(suggestion_id, baseline_kwh, actual_kwh, weather_adjusted_kwh, method, measured_at)`: the M&V record promised on slide 6.

### 6.7 `knowledge` (RAG, pgvector)

- `document(id, title, doc_type, lang, source_url, version, license_note, published_at)`.
- `chunk(id bigint identity, document_id, ord, body, tsv tsvector, embedding vector(N), embedding_model, token_count)`: HNSW (cosine) on `embedding`, GIN on `tsv`, `simple` + `unaccent` text-search config for Vietnamese. `N` and `halfvec` vs `vector` are decided with the embedding model; the model name is stored per row so a model change is detectable.
- Graph-RAG nodes/edges: not designed now (YAGNI); revisit when Copilot needs it.

### 6.8 `ops` (pipeline and audit)

- `ingest_batch(id, source, home_id, started_at, finished_at, rows_in, rows_new, rows_dup, rows_bad, status, note)` and `ingest_checkpoint(source, series_id, last_ts)`: a re-run of the same file must be a no-op.
- Data-quality views: coverage per series per day, gaps longer than N minutes, series that stopped reporting.

## 7. Relationships (summary)

`users` 1—1 `home_member` N—1 `home` · `home` 1—N `meter`, `device`, `series`, `bill`, `alert`, `conversation`, `suggestion` · `device` 1—N `series` (kind `plug`/`device`) · `series` 1—N `reading` / `device_estimate` · `tariff_plan` 1—N `tariff_version` 1—N `tariff_tier`, `home` N—1 `tariff_plan` · `bill` 1—N `bill_item` · `document` 1—N `chunk`.
Foreign keys are real everywhere except into hypertables (no FK from `reading.series_id`; integrity is enforced by the ingest path and a check query).

## 8. Operating rules

- **Chunks and compression**: starting point is a 1-day chunk, compress after 2 days, `segmentby series_id`, `orderby ts DESC` [C]. The final numbers come from the simulation (chunk index size should fit comfortably in RAM). **The 1 m continuous aggregates are compressed too** (migration `f3a9c1e5b7d2`, ruling of Task 10c): `reading_1m` and `device_estimate_1m` run `timescaledb.compress`, `segmentby series_id`, `orderby bucket DESC`, with real-time aggregation left on; measured 19.1x / 23.1x (about 150 -> 7 bytes per row) on a scratch copy of one month of House 1 (not on the full audit data, which was left uncompressed), where the uncompressed 1 m aggregates of the audit data were 3x the size of the compressed raw tables. `ops.set_policies` adds a compression policy on each of them with `compress_after` 14 days, which must stay above the 1 m refresh `start_offset` (7 days) so a refresh policy never finds its window converted (TimescaleDB docs, "Compress continuous aggregates"). The 1 h / 1 d aggregates are tiny and stay uncompressed. Refreshing a bucket range that sits in compressed 1 m chunks, and building 1 h / 1 d from compressed 1 m, were tested (`tests/db/test_cagg_compression.py`).
- **Retention** [C]: raw `reading`/`device_estimate` and the 1 m aggregate ~13 months (year-over-year comparison and before/after M&V), 1 h and 1 d aggregates kept indefinitely. Retention is a policy (`drop_chunks`), never row `DELETE`. **Interplay with the aggregates (measured in the 10b drill):** dropping raw chunks leaves the 1 m / 1 h / 1 d buckets untouched; only the 1 m retention policy deletes old 1 m buckets (1 h / 1 d have no retention policy and survive). A refresh over a range whose raw chunks are gone DELETES its existing buckets, so `backfill_aggregates` is guarded: by default it compares, per local day, the rows already materialized in a view with the aggregated raw rows still present (raw rows are never deleted except by retention), skips exactly the days where materialized exceeds raw (dropped chunks, a gap from a manual `drop_chunks`, a lone misdated row that recreated an old chunk) and returns them as skipped windows; fresh history and late rows are refreshed as usual (`allow_missing_raw=True` is the explicit opt-in for rebuilding from scratch or for rows deliberately removed or flagged after being aggregated). The check scans the raw rows of the window once per family. Known limit: the guard compares the materialized `n` with the raw rows still present per series and local day, so late rows of the same series on a partly dropped local day that bring the raw count back to (or above) the materialized `n` hide the loss; passing the guard does not prove the raw rows are intact.
- **Ingest path** [C]: one service function in the backend takes `(meter serial, source_channel, ts, value, quality)` rows, resolves `series_id` through `series(meter_id, source_channel)`, and writes as `wattprint_ingest`. The REFIT loader is a CLI that calls this function; a future meter HTTP endpoint (out of scope now) calls the same function, so REFIT really does use the production path.
- **Ingest writes**: batches with `ON CONFLICT DO NOTHING` (measured data) or `DO UPDATE` (estimates); per-series checkpoint; late data older than the aggregate refresh window is picked up by the Python helper `app/services/aggregates.py::backfill_aggregates` (async, AUTOCOMMIT connection only; `refresh_continuous_aggregate` cannot run in a transaction or a function, so never `CALL` an SQL procedure for it).
- **Reading rule**: all dashboards and Copilot tools read the aggregates; raw tables only for short windows, ingest lag and audits.
- **Roles** [C]: migrations run as the database owner login (`POSTGRES_USER`; no separate owner role exists), `wattprint_app` (API: DML on its tables, issues scope tokens), `wattprint_ingest` (INSERT on readings and `ops`), `wattprint_copilot_ro` (SELECT on a whitelist, `statement_timeout = 5s`). Decision: views, not Row Level Security. The Copilot reads only `copilot_ro.*` views (owned by the migration owner, `security_barrier`) plus `knowledge.*`, `catalog.*` and the tariff tables. Scoping is by an opaque per-request token: `wattprint_app` inserts a row in `copilot.scope_token` (random uuid, 5 minute expiry, readable only by the app), the Copilot session sets `app.copilot_token`, and the `SECURITY DEFINER` function `copilot_ro.current_home()` resolves it; a missing, empty, malformed, unknown or expired token returns NULL, so every view returns zero rows (fails closed). Backend contract (the token is a bearer secret): (a) set it only through a bind parameter (`SELECT set_config('app.copilot_token', $1, true)`) or connection startup options, never as an inlined literal, because free-form SQL can read sibling sessions' query text from `pg_stat_activity`; (b) use `is_local = true` inside the transaction (or `DISCARD ALL` / `RESET` on pool return) so a pooled connection never carries a previous home's token; (c) the Copilot SQL validator, working on the parse tree, must deny `pg_stat_activity`, `pg_stat_get_activity`, `pg_cancel_backend`, `pg_terminate_backend`, `set_config`, `current_setting` of `app.*` and any `pg_*` admin function; (d) keep Copilot transactions short: the 5-minute expiry is per transaction start (`expires_at > now()` is transaction time and a REPEATABLE READ transaction does not see a later token DELETE), not a hard cutoff. There is no pruning job: the table grows with unused tokens and the backend prunes it. Residual limits: (1) the role can change its own session settings (for example `set_config('statement_timeout', ...)`), so Copilot SQL must run on its OWN login connection to `wattprint_copilot_ro`, never via `SET ROLE` from the app login, behind a validator working on the parse tree (single SELECT, no `set_config` or `pg_*` admin functions); (2) all Copilot sessions share one role, so free-form SQL can reach `pg_stat_activity` text and `pg_cancel_backend` of sibling sessions; (3) PUBLIC keeps TEMP on the database and EXECUTE on `ops.set_policies` and `knowledge.immutable_unaccent`; (4) the role can read TimescaleDB internal metadata (hypertable names, chunk ranges), no per-home values; (5) `series.device_id`, `bill_item.device_id` and `suggestion.alert_id` may reference ids of another home (only UUIDs are exposed, joins return nothing).
- **Migrations**: one revision per change, with a working `downgrade` where possible, verified on an empty database (scratch databases and the audit rebuild stage) before merge.
- **Image**: pin `timescale/timescaledb:2.31.0-pg17`; upgrading is a deliberate change.

## 9. Audit and simulation (acceptance gate)

REFIT goes through the production ingest path: `Aggregate` → `reading` (`main` series), `Appliance1-9` → `reading` (`plug` series, standing in for measured ground truth), and a copy into `device_estimate` as a stand-in for NILM output. Dates are shifted to the present and `Asia/Ho_Chi_Minh` is used for day boundaries [C]. REFIT has no real per-home tariff, so the Vietnamese residential plan is applied, each date using the version valid then (1279 before 2026-11-01, 2892 from that day).

Staged: one house first (~7 M rows, ~70 M points), then all 20 houses (~1.19 B points) in the background. The `device_estimate` stand-in is loaded for 3 houses only, to keep disk down. Machine: Ryzen 7 7840H, 16 threads, 31 GB RAM, ~240 GB free on each of C: and D:; the Docker VM disk limit is **[TBV]** before stage 2, and if it is too small stage 2 is scaled down and extrapolated rather than skipped.

Order of steps, so policies do not corrupt the checks [C]:
1. Load with retention, compression and refresh policies **off**; REFIT is ~21 months of history, longer than the 13-month raw retention, so shifting it to end today with retention on would delete the data being tested.
2. Backfill the aggregates with the Python helper `app/services/aggregates.py::backfill_aggregates` (async, AUTOCOMMIT connection only, ends at the last closed bucket so `to_ts = now` is safe); run correctness, latency and idempotency checks.
3. Turn compression on (compress chunk by chunk during the stage 2 load to bound disk), re-run the checks.
4. Test retention and refresh policies separately in a drill on a scratch copy or a few chunks, not on the audit dataset.

Audit reference for the 1% gate [C, restated after the Task 10 audit]: zero-order-hold integration of raw samples per home-day, with the gap cap expressed in **minutes**, consistent with the `energy_wh` minute rule (a minute with at least one good sample counts as a whole minute, so the cap is about 2 minutes, not 5 x the median cadence: REFIT meters log about once per 62 s for long stretches, which a 5 x 7 s = 35 s cap treated as missing), and flagged time handled like the view (samples with `quality & 1 = 1` are dropped before integrating, so the previous good sample holds across them; they are not missing time). The gate applies to days with coverage >= 95%; days below that must show the matching low coverage instead. **Recorded result:** with the original reference (5 x median cadence, flagged = missing) 507 of 1,359 days exceeded 1% (max 54%); with the restated reference (hold across flagged, cap 120 s) the per-house p95 is 0.8-1.2% and the maximum 2.4-4.4%, with 16-30 days per house still over 1%. So the 1% per-day gate is **not met as an every-day bound**; the measured figure is "p95 about 1%, max 4.4% on days with coverage >= 95%". **The gate test (`test_energy_gate_one_percent`) measures this restated reference** (hold across flagged samples, cap 120 s); per house: 19 / 16 / 30 days over 1% (of 512 / 432 / 415), max 3.7 / 2.4 / 4.4%, p95 0.80 / 0.92 / 1.22%. The original reference is kept only as a recorded diagnostic (129 / 152 / 226 days over 1%, max 54%). Details and the evidence: `docs/database-audit.md`, section "Verdicts". Whether to keep an every-day 1% gate or adopt the p95 formulation is the owner's decision; until then the audit test stays an xfail carrying the numbers.

Pass criteria (targets to be confirmed against the first run, not promises):
1. **Idempotency**: loading the same file twice leaves row counts and aggregates identical.
2. **Correctness** (recorded result and the open decision: the restated reference below and `docs/database-audit.md`, "Verdicts"): `energy_wh` from `reading_1d` versus exact integration of raw samples within 1% per home-day; kWh totals match; gaps appear as gaps.
3. **Read latency**: Meter Day/Week/Month at ≤ 2000 points, "Now" latest value, device list and bill page each return fast enough for an interactive app (target p95 under 100 ms; "Now" under 20 ms). Plans checked with `EXPLAIN (ANALYZE, BUFFERS)`.
4. **Ingest throughput and growth**: rows/s, compression ratio, storage per home-year, and the extrapolated daily write volume at 10,000 homes.
5. **Failure drills**: duplicate batch, out-of-order and late data, a gap longer than an hour, `Issues`-flagged rows, a stopped refresh job (reads stay correct, only slower).
6. **Isolation**: `copilot_ro` cannot read another home or write anything.
7. **Rebuild**: empty volume → all migrations → seed → ingest, with no manual step.

## 10. Process notes (improvements to the requested flow)

- Compatibility is verified by running it (section 4), not by reading docs. Anything still unproven is marked **[TBV]** and becomes an explicit task.
- A builder check on this spec happened before approval (an independent reader raised 7 questions; all were settled with a marked [C] call in this document, none needed a user decision, though the user can overturn any of them).
- The final short document (`docs/database-design.md`) is written from the audited result, so numbers in it are measured, not assumed.

- **Ruling after the Task 10 audit (Tasks 10a-10c):** (1) the 1 m aggregates are compressed (section 8); (2) `backfill_aggregates` refuses by default to refresh ranges whose raw data is gone; (3) the energy reference of section 9 uses a cap in minutes and holds across flagged samples, and the gate result is stated as measured; (4) houses 4-20 were not loaded, growth for 10,000 homes is extrapolated from houses 1-3 (`docs/database-audit.md`, extrapolation scenarios).

## 11. Left to the builder

Exact column types and constraint names, index naming (follow the repo's naming convention in `app/database.py`), seed values for `device_type`, the embedding dimension, the minimum cohort size, and the final chunk/compression numbers from the simulation.
