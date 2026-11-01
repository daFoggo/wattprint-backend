# WattPrint Database Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the WattPrint database (schemas, hypertables, continuous aggregates, roles, ingest path, REFIT loader) and prove it with an audit/simulation, ending in a short design document.

**Architecture:** Hand-written Alembic revisions on top of the existing two (`e8d6cdf24fe4`, `a1c3f5b7d9e2`). Relational tables get SQLAlchemy models in `app/models/<domain>.py`; hypertables and continuous aggregates exist only in migrations (raw SQL) with thin `sa.Table` objects for the ingest writer. One ingest service function is the only writer of readings; the REFIT loader is a CLI that calls it. Dashboards read only continuous aggregates through `app/services/meter.py`.

**Tech Stack:** PostgreSQL 17.11, TimescaleDB 2.31.0, pgvector 0.8.1 (image `timescale/timescaledb:2.31.0-pg17`), SQLAlchemy 2.1 async + asyncpg 0.32, Alembic 1.20, pgvector-python, pytest-asyncio, uv, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-01-database-design-design.md` (read it first; section numbers below refer to it).

## Global Constraints

- Image pinned to `timescale/timescaledb:2.31.0-pg17`; extensions `timescaledb`, `vector`, `unaccent`, `pg_trgm`. No `timescaledb_toolkit`.
- Schemas: `core`, `catalog`, `energy`, `billing`, `insight`, `copilot`, `knowledge`, `ops`; `public.users`, `public.refresh_tokens` untouched.
- All timestamps `timestamptz` (UTC). Money `numeric`. Power `real`, derived energy `double precision`. Native `uuid` for relational PKs; `series_id int identity` for hypertable keys. No FK into hypertables.
- Hypertables `energy.reading` and `energy.device_estimate`: PK `(series_id, ts)`, chunk interval 1 day, `compress_segmentby = series_id`, `compress_orderby = ts DESC`, no secondary indexes.
- Aggregates: `reading_1m → reading_1h → reading_1d` and `device_estimate_1m → _1h → _1d`; real-time aggregation on (`materialized_only = false`); daily buckets cut in `Asia/Ho_Chi_Minh`; columns `avg_w, min_w, max_w, last_w, n, energy_wh` plus `covered_minutes` at 1h/1d. Rows with `quality & 1 = 1` (source flagged bad) are excluded from `reading` aggregates [C].
- Energy rule: `_1m.energy_wh = avg_w * 60 / 3600` for buckets with `n >= 1`; `_1h`/`_1d` sum child `energy_wh`; missing time is 0 Wh, never filled; no mean of means (`avg_w` at 1h/1d is the sample-weighted mean `sum(avg_w*n)/sum(n)`).
- Policies are installed and removed by one SQL function `ops.set_policies(enabled boolean)`: compression after 2 days, retention 400 days on raw tables and 1 m aggregates, 1 m refresh every minute (`start_offset` 7 days, `end_offset` 1 minute), 1 h refresh hourly (`start_offset` 30 days), 1 d refresh hourly (`start_offset` 60 days). Default after migration: enabled. Audit calls it with `false`.
- Roles `wattprint_app`, `wattprint_ingest`, `wattprint_copilot_ro`: explicit per-table grants only, never `ALL TABLES`. Passwords from env `APP_DB_PASSWORD`, `INGEST_DB_PASSWORD`, `COPILOT_DB_PASSWORD`; a role without its env var is created `NOLOGIN`. The Copilot role reads only views in schema `copilot_ro` filtered by `home_id = current_setting('app.home_id')::uuid`, plus `knowledge.*` and `catalog.*`; it has no write privileges and `statement_timeout = '5s'`. Row Level Security on continuous aggregates is not used.
- Timezone: `core.home.timezone` has `CHECK (timezone = 'Asia/Ho_Chi_Minh')`.
- Embedding column `vector(1024)` with `embedding_model text not null` [C].
- `MIN_COHORT_HOMES = 10`: `insight.cohort_stat` has `CHECK (n_homes >= 10)` [C].
- Constraint and index names follow the naming convention in `app/database.py`. Python 3.12, ruff line length 100, `ruff check` clean.
- Tests run inside the stack: `docker compose exec api pytest <path> -v`. DB tests use a scratch database created per session, never `wattprint`.
- Commits go on the local branch `feat/database-design` only, one per task, staging explicit paths (never `git add -A`: `dataset/` and other untracked user files must stay unstaged). Nothing is pushed. "Checkpoint" steps mean run the checks, then commit that task.

## Review Focus

- Re-loading the same REFIT file twice: identical row counts and aggregates, `rows_dup` reported, nothing double counted.
- A reading at 2013-10-09 16:59:59 UTC vs 17:00:00 UTC lands in different daily buckets (local midnight is 17:00 UTC).
- A gap longer than 5 × the cadence (REFIT has gaps over 1 hour) produces missing minutes in `reading_1m`, `covered_minutes` below expected, and no invented energy.
- `wattprint_copilot_ro` for home A cannot see home B through any view, cannot call `INSERT/UPDATE/DELETE`, and a runaway query is cancelled at 5 s.
- A reading older than the 1 m refresh `start_offset` (7 days) is picked up by the targeted backfill helper, not silently left out of the aggregate.

---

## File Structure

- `docker-compose.yml`: pin image, mount `./dataset:/data:ro` for `api`.
- `alembic/versions/20261101_*`: one revision per task 1-6 (chain after `a1c3f5b7d9e2`).
- `app/models/{catalog,core,energy,billing,insight,copilot,knowledge,ops}.py` + `app/models/__init__.py` exports.
- `app/services/{ingest,billing,meter}.py`; `app/cli/{provision_refit,load_refit}.py`; `app/seed/refit_metadata.json`.
- `scripts/build_refit_metadata.py` (one-off, stdlib only, reads `dataset/MetaData_Tables.xlsx`).
- `tests/db/` (scratch-DB tests), `tests/audit/` (marker `audit`, run on demand), `tests/data/refit_sample.csv`.
- `docs/database-audit.md` (measured results), `docs/database-design.md` (final short document).

---

### Task 1: Foundation: image pin, extensions, schemas, roles, test harness

**Files:**
- Modify: `docker-compose.yml`, `.env.example`, `pyproject.toml` (add `pgvector`), `uv.lock`
- Create: `alembic/versions/20261101_<rev>_foundation.py`, `tests/db/conftest.py`, `tests/db/test_foundation.py`

**Interfaces:**
- Produces: fixture `scratch_dsn() -> str` (session scope: creates `wattprint_test_<hex>` on the compose DB, runs `alembic upgrade head` via subprocess with env `DATABASE_URL` pointing at it, drops it at teardown) fixture `conn` (async SQLAlchemy `AsyncConnection` on it, rolled back per test), fixture `session` (an `AsyncSession` bound to that same rolled-back connection) and fixture `autocommit_conn` (a separate `AsyncConnection` with `isolation_level="AUTOCOMMIT"` for `CALL refresh_continuous_aggregate` and the Python helper `backfill_aggregates`; tests that use it clean up the rows they committed, keyed by their own `series_id`/`home_id`). Revision functions create schemas, extensions and the three roles; `ops.set_policies` is added in Task 3.

- [ ] **Step 1: Write failing tests** in `tests/db/test_foundation.py`: `test_extension_versions` (rows of `pg_extension` include `timescaledb` 2.31.0, `vector` 0.8.1, `unaccent`, `pg_trgm`), `test_schemas_exist` (all eight schemas), `test_roles_exist_nologin_without_password`, `test_ingest_role_cannot_create_table`.
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_foundation.py -v`. Expected: FAIL (fixtures/revision missing).
- [ ] **Step 3:** Pin the image in compose, add the env vars to `.env.example` (empty), `uv add pgvector`, write the revision (extensions, schemas, roles with `NOLOGIN` fallback, `ALTER ROLE wattprint_copilot_ro SET statement_timeout = '5s'`) and the fixtures. `docker compose up -d db` after pinning (volume is recreated only if you choose; the revision uses `IF NOT EXISTS`).
- [ ] **Step 4:** Run the tests. Expected: PASS. Also run `docker compose exec api alembic upgrade head` on the real DB and `alembic downgrade -1 && alembic upgrade head`; both succeed.
- [ ] **Step 5: Checkpoint:** `ruff check .` clean.

### Task 2: `catalog` and `core` tables

**Files:**
- Create: `app/models/{catalog,core}.py`, revision `..._catalog_core.py`, `tests/db/test_core.py`
- Modify: `app/models/__init__.py`

**Interfaces:**
- Produces: models `Metric(event_type, unit, aggregation)`, `DeviceType(code, label_vi, label_en, typical_watts, tip_text)`, `Home`, `HomeMember`, `HomeInvite`, `Meter`, `Device`, `DeviceAlertRule` with columns exactly as spec 6.1/6.2. Seeds: metrics `power_w` (W, mean), `energy_wh` (Wh, energy), `reactive_power_var`, `voltage_v`, `current_a`; device types covering the Sense list in the screenshots plus the REFIT names (fridge, freezer, fridge_freezer, washing_machine, washer_dryer, tumble_dryer, dishwasher, television, computer, microwave, kettle, toaster, hifi, electric_heater, router, other).

- [ ] **Step 1: Write failing tests**: `test_user_can_join_only_one_home` (second `home_member` row for the same `user_id` raises `IntegrityError`), `test_home_timezone_check`, `test_billing_cycle_day_range` (0 and 29 rejected), `test_invite_stores_hash_only` (no plaintext column exists), `test_meter_serial_unique`, `test_device_validity_range_check` (`active_to > active_from`), `test_metric_seed_has_power_w`.
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_core.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement models and the revision (FKs real; `home.tariff_plan_code` added without FK now, FK added in Task 5).
- [ ] **Step 4:** Run the tests. Expected: PASS. Run `alembic downgrade -1 && upgrade head`.
- [ ] **Step 5: Checkpoint:** `ruff check .`.

### Task 3: `energy` hypertables and policy function

**Files:**
- Create: `app/models/energy.py`, revision `..._energy_tables.py`, `tests/db/test_energy_tables.py`

**Interfaces:**
- Produces: models `Series`, `InferenceRun`, `WeatherHourly`; `sa.Table` objects `reading_table` (`ts, series_id, value, quality`) and `device_estimate_table` (`ts, series_id, value, run_id`) in `app/models/energy.py`; SQL function `ops.set_policies(enabled boolean) returns void`.

- [ ] **Step 1: Write failing tests**: `test_reading_is_hypertable_with_one_day_chunks`, `test_series_main_unique_per_home_metric` (two `main` rows for same home+metric rejected, NULLS NOT DISTINCT), `test_series_kind_device_requires_device_id` (CHECK), `test_compress_settings` (segmentby `series_id`), `test_on_conflict_do_nothing_on_compressed_chunk`, `test_set_policies_toggle` (job rows appear with `true`, disappear with `false`, idempotent when called twice).
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_energy_tables.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. `ops.set_policies` adds/removes the compression and retention policies (raw tables) now; Task 4 extends it with the aggregate refresh and 1 m retention policies, so keep the function in a form Task 4 can `CREATE OR REPLACE`.
- [ ] **Step 4:** Run the tests. Expected: PASS; downgrade/upgrade round trip.
- [ ] **Step 5: Checkpoint:** `ruff check .`.

### Task 4: Continuous aggregates

**Files:**
- Create: revision `..._energy_aggregates.py`, `tests/db/test_aggregates.py`

**Interfaces:**
- Produces: views `energy.reading_1m|_1h|_1d` and `energy.device_estimate_1m|_1h|_1d`, columns per Global Constraints; Python helper `app/services/aggregates.py::backfill_aggregates(conn, from_ts, to_ts)` (async, AUTOCOMMIT connection only; an SQL procedure is impossible) that refreshes the six aggregates in order; extended `ops.set_policies`.

- [ ] **Step 1: Write failing tests** (insert known readings, call `backfill_aggregates` on an autocommit connection): `test_1m_energy_rule` (three samples 100/200/300 W in one minute → `avg_w` 200, `energy_wh` 200*60/3600), `test_1h_avg_is_sample_weighted`, `test_gap_leaves_missing_minutes` (samples at minute 0 and minute 10 → `covered_minutes` 2 at 1h, `energy_wh` equals the sum of the two minutes only), `test_daily_bucket_cut_at_17_utc` (16:59:59 and 17:00:00 UTC in different `_1d` buckets), `test_quality_flagged_rows_excluded_from_reading_aggregates`, `test_device_estimate_not_filtered_by_quality`, `test_realtime_aggregation_on` (row inserted after last refresh visible in `_1m`), `test_late_row_needs_backfill` (row older than 7 days absent until `backfill_aggregates` covers it).
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_aggregates.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the revision: create the six views `WITH NO DATA` inside the transaction, set `materialized_only = false`, then extend `ops.set_policies`. Daily view uses `time_bucket('1 day', bucket, 'Asia/Ho_Chi_Minh')` over the 1 h view. If Timescale rejects a timezone-aware bucket on a hierarchical aggregate (spec TBV), fall back to `time_bucket('1 day', bucket, origin => '2000-01-01 17:00:00+00')` and record the finding in `docs/database-audit.md`.
- [ ] **Step 4:** Run the tests. Expected: PASS; downgrade/upgrade round trip (downgrade drops views in reverse order).
- [ ] **Step 5: Checkpoint:** `ruff check .`.

### Task 5: `billing` tables, tariff seed and bill computation

**Files:**
- Create: `app/models/billing.py`, `app/services/billing.py`, revision `..._billing.py`, `tests/db/test_billing.py`
- Modify: `app/models/__init__.py`

**Interfaces:**
- Consumes: `energy.reading_1d`, `core.home.billing_cycle_day`, `home.tariff_plan_code`.
- Produces: models `TariffPlan(code, name, currency)`, `TariffVersion`, `TariffTier`, `Bill`, `BillItem`; FK `home.tariff_plan_code → billing.tariff_plan.code`; `async def compute_bill(session: AsyncSession, home_id: UUID, period_start: date) -> Bill` (idempotent upsert on `(home_id, period_start)`; period end from `billing_cycle_day`; tiers applied cumulatively on the cycle's total kWh; `coverage = covered_minutes / expected_minutes`; status `partial` when coverage < 0.95, otherwise `open` or `closed` if the period ended; per-device `bill_item` rows use share of kWh from `device_estimate_1d` applied to the total amount, plus `always_on`/`other` labels where present).

- [ ] **Step 1: Write failing tests**: `test_amount_under_decision_1279_six_tiers` (350 kWh in a period starting 2026-10-01 → before-VAT 907,000: 50×1,984 + 50×2,050 + 100×2,380 + 100×2,998 + 50×3,350), `test_amount_under_decision_2892_five_tiers` (350 kWh in a period starting 2026-11-01 → before-VAT 853,100: 100×1,901 + 100×2,289 + 150×2,894), `test_vat_uses_version_vat_rate` (`vat_amount = round(before_vat × vat_rate)`, `amount_total` is their sum), `test_version_chosen_by_period_start`, `test_straddle_flag_when_version_changes_inside_period` (period 2026-10-15 to 2026-11-14 → `tariff_straddle` true, 1279 prices), `test_compute_bill_is_idempotent`, `test_partial_status_when_coverage_low`, `test_device_item_share` (device 40% of kWh gets 40% of the amount), `test_bill_unique_per_home_period`.
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_billing.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Seed one plan `vn_residential` with two versions (prices before VAT, đồng/kWh; user-supplied, 2892 cross-checked against the Thanh Nien report of 2026-11-01). Decision 1279/QĐ-BCT, `valid_from` 2025-05-10, `valid_to` 2026-10-31: 0-50 → 1,984; 51-100 → 2,050; 101-200 → 2,380; 201-300 → 2,998; 301-400 → 3,350; 401+ → 3,460. Decision 2892, `valid_from` 2026-11-01, no `valid_to`: 0-100 → 1,901; 101-200 → 2,289; 201-400 → 2,894; 401-700 → 3,456; 701+ → 3,844. Record both in `source_doc`. The `vat_rate` is **not** given by either source: take it from an official source on VAT for electricity in force for each version, and if it cannot be verified, stop and report instead of guessing. `bill` gets a boolean column `tariff_straddle`. No proration and no mid-period split (spec 6.4).
- [ ] **Step 4:** Run the tests. Expected: PASS; round trip.
- [ ] **Step 5: Checkpoint:** `ruff check .`.

### Task 6: `insight`, `copilot`, `knowledge`, `ops` tables and the Copilot read role

**Files:**
- Create: `app/models/{insight,copilot,knowledge,ops}.py`, revision `..._domain_tables.py`, `tests/db/test_domain_tables.py`, `tests/db/test_copilot_role.py`
- Modify: `app/models/__init__.py`

**Interfaces:**
- Produces: models for every table in spec 6.5-6.8 (`device_cycle` as a hypertable with 30-day chunks created in the revision; `ops.ingest_batch`, `ops.ingest_checkpoint`); `knowledge.chunk` with `tsv` generated from `body` using config `simple` + `unaccent`, GIN on `tsv`, HNSW cosine on `embedding`; views in schema `copilot_ro`: `reading_1m`, `reading_1h`, `reading_1d`, `device_estimate_1m`, `device_estimate_1h`, `device_estimate_1d`, `device`, `bill`, `bill_item`, `alert`, `device_cycle`, each joining `energy.series`/`core.*` and filtered by `home_id = current_setting('app.home_id')::uuid` (`security_barrier`); grants per Global Constraints.

- [ ] **Step 1: Write failing tests**: `test_cohort_min_size_check`, `test_chunk_fts_matches_unaccented_vietnamese` (query `tiet kiem dien` matches body `Tiết kiệm điện`), `test_chunk_hnsw_nearest` (1024-dim vectors), `test_device_cycle_is_hypertable`, `test_ingest_checkpoint_pk`; role tests as `wattprint_copilot_ro` (needs a login password set by the fixture via `ALTER ROLE ... PASSWORD`): `test_copilot_sees_only_own_home`, `test_copilot_cannot_write`, `test_copilot_cannot_read_base_tables` (`energy.reading`, `core.home_member`, `public.users` denied), `test_copilot_statement_timeout` (`pg_sleep(6)` cancelled).
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_domain_tables.py tests/db/test_copilot_role.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement models, revision, views and grants.
- [ ] **Step 4:** Run the tests plus the whole `tests/db`. Expected: PASS; round trip of the full chain (`downgrade base` then `upgrade head` on a scratch DB).
- [ ] **Step 5: Checkpoint:** `ruff check .`.

### Task 7: Ingest service

**Files:**
- Create: `app/services/ingest.py`, `tests/db/test_ingest.py`

**Interfaces:**
- Consumes: `reading_table`, `device_estimate_table`, models `Meter`, `Series`; tables `ops.ingest_batch`, `ops.ingest_checkpoint`.
- Produces:
  - `@dataclass ReadingRow: ts: datetime; channel: str; value: float; quality: int = 0`
  - `@dataclass IngestResult: batch_id: UUID; rows_in: int; rows_new: int; rows_dup: int; rows_bad: int`
  - `async def ingest_readings(session: AsyncSession, meter_serial: str, rows: Sequence[ReadingRow], source: str) -> IngestResult`: resolves `series_id` through `(meter_id, source_channel)`; unknown channel or non-finite value counts as `rows_bad` and is not written; bulk path = asyncpg `copy_records_to_table` into a temp table then `INSERT ... ON CONFLICT DO NOTHING`; writes one `ops.ingest_batch` row and advances `ops.ingest_checkpoint` per series; returns counts that satisfy `rows_in = rows_new + rows_dup + rows_bad`.
  - `async def ingest_estimates(session, run_id: int, rows: Sequence[tuple[datetime, int, float]]) -> int` (upsert, latest run wins).

- [ ] **Step 1: Write failing tests**: `test_ingest_counts_add_up`, `test_second_identical_batch_is_all_dup`, `test_unknown_channel_counted_bad`, `test_nan_value_counted_bad`, `test_out_of_order_rows_accepted`, `test_checkpoint_advances_to_max_ts`, `test_estimates_upsert_latest_run_wins`.
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_ingest.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement per the signatures.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Checkpoint:** `ruff check .`.

### Task 8: REFIT metadata, provisioning and loader

**Files:**
- Create: `scripts/build_refit_metadata.py`, `app/seed/refit_metadata.json`, `app/cli/__init__.py`, `app/cli/provision_refit.py`, `app/cli/load_refit.py`, `tests/data/refit_sample.csv` (first 300 rows of House 1), `tests/db/test_refit_loader.py`
- Modify: `docker-compose.yml` (mount `./dataset:/data:ro` on `api`)

**Interfaces:**
- Consumes: `ingest_readings`, models from tasks 2-3.
- Produces: `refit_metadata.json` (`{"<house>": {"occupancy", "type", "size", "channels": {"Appliance1": {"name", "brand", "model", "note"}, ...}}}`, built from the spreadsheet; rows named `???` get `name: "unknown"`); `async def provision_house(session, house: int, owner_email: str) -> UUID` (creates a user if absent, home with `home_type` and `occupants` from metadata, meter `REFIT-H<house>`, `main` series from channel `Aggregate`, one `device` + `plug` series per appliance channel); `async def load_house(session, house: int, csv_path: Path, shift_days: int = 0, batch_rows: int = 200_000, limit_rows: int | None = None) -> IngestResult` (streams the CSV, `Time` read as UTC, `Issues == 1` sets `quality |= 1` on all channels of that row, Aggregate and Appliance columns become `ReadingRow`s); CLI `python -m app.cli.load_refit --house N [--shift-days D] [--limit-rows R]`.

- [ ] **Step 1: Write failing tests**: `test_provision_creates_home_meter_and_ten_series`, `test_provision_is_idempotent`, `test_load_sample_counts` (300 rows × 10 channels = 3000 readings, 0 bad), `test_reload_sample_is_all_dup`, `test_issues_flag_sets_quality_bit`, `test_shift_days_moves_timestamps_not_values`.
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_refit_loader.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. The metadata script uses only the stdlib (zip + XML), as already proven on this spreadsheet.
- [ ] **Step 4:** Run the tests; then `docker compose exec api python -m app.cli.load_refit --house 1 --limit-rows 100000` against a scratch DB and check counts by SQL. Expected: 1,000,000 readings.
- [ ] **Step 5: Checkpoint:** `ruff check .`.

### Task 9: Read model service

**Files:**
- Create: `app/services/meter.py`, `tests/db/test_meter_service.py`

**Interfaces:**
- Consumes: aggregates from Task 4.
- Produces:
  - `LADDER = ("1m", "5m", "15m", "30m", "1h", "3h", "6h", "1d")`
  - `def pick_step(since: datetime, until: datetime, max_points: int) -> str` (finest step keeping the point count ≤ `max_points`; window capped at 90 days and 2000 buckets as in spec 6.3)
  - `async def meter_series(session, home_id: UUID, since: datetime, until: datetime, max_points: int = 600) -> list[Point]` with `Point(ts, avg_w, min_w, max_w, energy_wh)`; reads `reading_1m|_1h|_1d` only and stops at the last closed minute (`bucket < date_trunc('minute', now())`); 5 m/15 m/30 m/3 h/6 h steps are `time_bucket` re-buckets of the next finer aggregate.
  - `async def latest_power(session, home_id: UUID) -> LatestPower | None` (`LatestPower(ts, watts)`, from `reading_1m` last bucket).
  - `async def device_breakdown(session, home_id: UUID, since: datetime, until: datetime) -> list[DeviceEnergy]` (`DeviceEnergy(device_id, kwh, share)` from `device_estimate_1h|_1d`).

- [ ] **Step 1: Write failing tests**: `test_pick_step_ladder` (1 day at 600 points → `5m`; 30 days → `1h`; 90 days → `3h`), `test_pick_step_rejects_window_over_90_days`, `test_meter_series_excludes_open_minute`, `test_meter_series_never_touches_raw_table` (run with SELECT revoked on `energy.reading` for the test role), `test_latest_power`, `test_device_breakdown_shares_sum_to_one`.
- [ ] **Step 2:** Run `docker compose exec api pytest tests/db/test_meter_service.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Checkpoint:** `ruff check .`; whole `tests/db` green.

### Task 10: Audit and simulation

**Files:**
- Create: `tests/audit/conftest.py`, `tests/audit/test_audit.py`, `app/cli/audit_report.py`, `docs/database-audit.md`
- Modify: `pyproject.toml` (register marker `audit`; default `pytest` run skips it)

**Interfaces:**
- Consumes: everything above. Uses a persistent database `wattprint_audit` (created and migrated by the audit conftest, reused across stages).
- Produces: `docs/database-audit.md` with measured numbers for each spec 9 criterion, written by `app/cli/audit_report.py` from the audit run's JSON output.

- [ ] **Step 1: Write the audit tests** (marker `audit`, ordered stages): `test_stage0_docker_disk_limit` (records Docker VM disk and decides stage 2 size), `test_idempotency` (load House 1 first 1,000,000 rows twice; counts and `reading_1d` sums identical), `test_energy_vs_exact_integration` (per home-day with coverage ≥ 95%: zero-order-hold integration of raw samples, gap > 5 × median cadence treated as missing, error ≤ 1%; days below 95% must show the matching coverage), `test_read_latency` (meter day/week/month at ≤ 2000 points, `latest_power`, device list, `compute_bill`: p95 recorded, targets 100 ms and 20 ms for `latest_power`, plans captured with `EXPLAIN (ANALYZE, BUFFERS)`), `test_failure_drills` (duplicate batch, out-of-order, gap > 1 h, `Issues` rows, stopped refresh job leaves reads correct), `test_copilot_isolation` (same checks as Task 6 on loaded data), `test_rebuild_from_empty` (drop database, migrate, seed, load a 10,000-row sample, no manual step).
- [ ] **Step 2:** Run `docker compose exec api pytest tests/audit -m audit -k "stage0 or idempotency" -v`. Expected: FAIL (harness missing), then PASS after the conftest exists.
- [ ] **Step 3:** Execute the stages in this order and keep policies off until step (c): (a) `SELECT ops.set_policies(false)`; load House 1 fully, then Houses 2-3 plus the `device_estimate` stand-in (copy of the plug series) for Houses 1-3; run the Python helper `backfill_aggregates` on an AUTOCOMMIT connection; run the correctness, latency, idempotency and drill tests; (b) load Houses 4-20 (`reading` only), compressing chunks as the load proceeds to bound disk, scaled down per `stage0` if the disk limit demands it; rerun latency and report growth, rows/s, compression ratio, storage per home-year and extrapolated 10,000-home daily volume; (c) `SELECT ops.set_policies(true)`; test retention and refresh policies only on a scratch copy of a few chunks; (d) run `test_rebuild_from_empty`.
- [ ] **Step 4:** Run `docker compose exec api python -m app.cli.audit_report > docs/database-audit.md`. Review the numbers; any failed criterion is a defect to fix in the owning task, not a note.
- [ ] **Step 5: Checkpoint:** `ruff check .`; default `pytest` (without audit) still green.

### Task 11: Final design document

**Files:**
- Create: `docs/database-design.md`

- [ ] **Step 1:** Write the short document from the audited result: why this stack, the shape of the data (one paragraph + a table list), read/write paths, operating rules, the measured results table taken from `docs/database-audit.md`, and the open items that remain. Natural prose, English technical terms untranslated, no unmeasured claims.
- [ ] **Step 2:** Check every number in it against `docs/database-audit.md`; check each table name against the migrations (`grep`). Expected: no mismatch.
- [ ] **Step 3: Checkpoint:** `git diff --check`.

---

## Self-review

- **Spec coverage:** 6.1-6.2 → Task 2; 6.3 → Tasks 3-4; 6.4 → Task 5; 6.5-6.8 and roles → Task 6; ingest path (section 8) → Tasks 7-8; zoom ladder → Task 9; section 9 criteria 1-7 → Task 10 (idempotency, correctness, latency, throughput/growth, drills, isolation, rebuild); final document → Task 11. Section 8 retention, compression and image pin → Tasks 1, 3, 4.
- **Types:** `ReadingRow`/`IngestResult`/`ingest_readings` defined in Task 7 and used in Task 8; `Point`/`meter_series` in Task 9 used in Task 10; `ops.set_policies` (Tasks 3-4) and the Python helper `backfill_aggregates` (Task 4) defined and used in Task 10.
- **Review Focus** items map to tests: re-load (T7, T8, T10), day boundary (T4), gaps (T4, T10), copilot isolation (T6, T10), late data (T4).
- **Open decisions made here [C]:** quality-flagged rows excluded from `reading` aggregates; `MIN_COHORT_HOMES = 10`; embedding `vector(1024)`; Copilot reads views, not RLS; policy function `ops.set_policies`.
