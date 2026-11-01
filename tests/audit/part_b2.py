"""Audit part B stages on scratch databases: cagg compression (E), policy drill (F),
extrapolation (I), harness check (H)."""

# ruff: noqa: E501 - dense audit scripts with long SQL strings

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.aggregates import backfill_aggregates
from tests.audit import results
from tests.audit.part_b import ROOT, log, summarize_ms
from tests.audit.support import create_scratch, drop_scratch, make_engine, scratch_url


async def copy_slices(scratch_dsn: str, slices: list[tuple[datetime, datetime]],
                      with_estimates: bool) -> dict:
    """Copy House 1's rows of the given [from, to) slices into a scratch database.

    Every copied series becomes the `main` series of its own scratch home (same series_id), which
    satisfies the series constraints without copying devices.
    """
    src = make_engine()
    dst = create_async_engine(scratch_dsn)
    counts: dict = {}
    try:
        async with src.connect() as sc, dst.connect() as dc:
            sids = [r[0] for r in await sc.execute(text(
                "SELECT s.series_id FROM energy.series s JOIN core.home h ON h.id = s.home_id "
                "WHERE h.name = 'REFIT House 1' ORDER BY 1"))]
            for sid in sids:
                await dc.execute(text(
                    "WITH h AS (INSERT INTO core.home (name) VALUES ('scratch') RETURNING id) "
                    "INSERT INTO energy.series (series_id, home_id, kind, metric, unit) "
                    "OVERRIDING SYSTEM VALUE SELECT :s, id, 'main', 'power_w', 'W' FROM h"),
                    {"s": sid})
            await dc.commit()
            raw_src = (await sc.get_raw_connection()).driver_connection
            raw_dst = (await dc.get_raw_connection()).driver_connection
            for table, cols in (("reading", ["ts", "series_id", "value", "quality"]),
                                ("device_estimate", ["ts", "series_id", "value", "run_id"])):
                if table == "device_estimate" and not with_estimates:
                    continue
                total = 0
                for a, b in slices:
                    rows = await raw_src.fetch(
                        f"SELECT {', '.join(cols)} FROM energy.{table} "
                        "WHERE ts >= $1 AND ts < $2 AND series_id = ANY($3::int[])", a, b, sids)
                    if table == "device_estimate":
                        rows = [(r[0], r[1], r[2], None) for r in rows]
                    await raw_dst.copy_records_to_table(
                        table, records=[tuple(r) for r in rows], columns=cols,
                        schema_name="energy")
                    total += len(rows)
                counts[table] = total
            await dc.commit()
    finally:
        await src.dispose()
        await dst.dispose()
    return counts


async def _size(c, name: str) -> int:
    return int(await c.scalar(text("SELECT hypertable_size(CAST(:n AS regclass))"), {"n": name}))


async def _mat_table(c, view: str) -> str:
    return await c.scalar(text(
        "SELECT format('%I.%I', materialization_hypertable_schema, "
        "materialization_hypertable_name) FROM timescaledb_information.continuous_aggregates "
        "WHERE view_name = :v"), {"v": view})


async def timed_backfill(eng, a: datetime, b: datetime) -> dict:
    """backfill_aggregates over [a, b) on an AUTOCOMMIT engine; seconds per refreshed view."""
    timings: dict[str, float] = {}
    t0: dict[str, float] = {}

    def before(conn, cursor, statement, parameters, context, executemany):
        if "refresh_continuous_aggregate" in statement:
            t0["t"] = time.perf_counter()

    def after(conn, cursor, statement, parameters, context, executemany):
        if "refresh_continuous_aggregate" in statement:
            view = parameters["v"] if isinstance(parameters, dict) else parameters[0]
            timings[view] = timings.get(view, 0.0) + time.perf_counter() - t0["t"]

    event.listen(eng.sync_engine, "before_cursor_execute", before)
    event.listen(eng.sync_engine, "after_cursor_execute", after)
    try:
        async with eng.connect() as c:
            await backfill_aggregates(c, a, b)
    finally:
        event.remove(eng.sync_engine, "before_cursor_execute", before)
        event.remove(eng.sync_engine, "after_cursor_execute", after)
    return {k: round(v, 2) for k, v in sorted(timings.items())}


# ------------------------------------------------------------------ E
async def stage_cagg_compression(args) -> None:
    name = "wattprint_audit_e"
    dsn = await create_scratch(name)
    month = (datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    counts = await copy_slices(dsn, [month], with_estimates=True)
    eng = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    out: dict = {"copied_rows": counts, "slice": "House 1, 2026-09 (all series incl. plugs)"}
    async with eng.connect() as c:
        t0 = time.perf_counter()
        out["backfill_seconds_per_view"] = await timed_backfill(eng, *month)
        out["backfill_seconds"] = round(time.perf_counter() - t0, 1)
        for fam in ("reading", "device_estimate"):
            view = f"energy.{fam}_1m"
            mat = await _mat_table(c, f"{fam}_1m")
            rows = await c.scalar(text(f"SELECT count(*) FROM {view}"))
            before = await _size(c, mat)
            await c.execute(text(
                f"ALTER MATERIALIZED VIEW {view} SET (timescaledb.compress = true, "
                "timescaledb.compress_segmentby = 'series_id', "
                "timescaledb.compress_orderby = 'bucket DESC')"))
            t1 = time.perf_counter()
            chunks = [r[0] for r in await c.execute(text(
                "SELECT format('%I.%I', chunk_schema, chunk_name) "
                "FROM timescaledb_information.chunks WHERE hypertable_schema = "
                "split_part(:m, '.', 1) AND hypertable_name = split_part(:m, '.', 2) "
                "AND NOT is_compressed"), {"m": mat})]
            for ch in chunks:
                await c.execute(text("SELECT compress_chunk(CAST(:c AS regclass))"), {"c": ch})
            after = await _size(c, mat)
            same = await c.scalar(text(f"SELECT count(*) FROM {view}"))
            out[f"{fam}_1m"] = {
                "rows": rows, "chunks_compressed": len(chunks), "bytes_before": before,
                "bytes_after": after, "ratio": round(before / after, 2),
                "bytes_per_row_before": round(before / rows, 1),
                "bytes_per_row_after": round(after / rows, 1),
                "compress_seconds": round(time.perf_counter() - t1, 1),
                "row_count_unchanged": same == rows,
            }
            log(f"{fam}_1m: {out[f'{fam}_1m']}")
        sid = await c.scalar(text("SELECT min(series_id) FROM energy.series"))
        lat = {}
        for label, sql in (
            ("5m_over_1d", "SELECT time_bucket('5 minutes', bucket) b, avg(avg_w), min(min_w), "
             "max(max_w), sum(energy_wh) FROM energy.reading_1m WHERE series_id = :s AND "
             "bucket >= '2026-09-20 17:00+00' AND bucket < '2026-09-21 17:00+00' GROUP BY 1 "
             "ORDER BY 1"),
            ("latest_minute", "SELECT bucket, last_w FROM energy.reading_1m WHERE series_id = :s "
             "AND bucket >= '2026-09-24 00:00+00' AND bucket < '2026-09-30 00:00+00' "
             "ORDER BY bucket DESC LIMIT 1"),
        ):
            ts = []
            for _ in range(31):
                t = time.perf_counter()
                await c.execute(text(sql), {"s": sid})
                ts.append((time.perf_counter() - t) * 1000)
            lat[label] = summarize_ms(ts[1:])
        out["latency_on_compressed_1m_ms"] = lat
    await eng.dispose()
    await drop_scratch(name)
    for k, v in out.items():
        results.record("cagg_compression", k, v)


# ------------------------------------------------------------------ F
async def _job(c, proc: str, table: str) -> int:
    return await c.scalar(text(
        "SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = :p AND "
        "hypertable_name = :t"), {"p": proc, "t": table})


async def _view_counts(c, a: datetime, b: datetime) -> dict:
    return {v: await c.scalar(text(f"SELECT count(*) FROM energy.reading_{v} "
                                   "WHERE bucket >= :a AND bucket < :b"), {"a": a, "b": b})
            for v in ("1m", "1h", "1d")}


async def _mat_counts(c, a: datetime, b: datetime) -> dict:
    out = {}
    for v in ("1m", "1h", "1d"):
        mat = await _mat_table(c, f"reading_{v}")
        out[v] = await c.scalar(text(f"SELECT count(*) FROM {mat} WHERE bucket >= :a "
                                     "AND bucket < :b"), {"a": a, "b": b})
    return out


async def _raw_count(c, a: datetime, b: datetime) -> int:
    return await c.scalar(text("SELECT count(*) FROM energy.reading WHERE ts >= :a AND ts < :b"),
                          {"a": a, "b": b})


async def _chunk_state(c) -> dict:
    row = (await c.execute(text(
        "SELECT count(*) AS total, count(*) FILTER (WHERE is_compressed) AS compressed "
        "FROM timescaledb_information.chunks WHERE hypertable_schema='energy' "
        "AND hypertable_name='reading'"))).one()
    return {"total": row.total, "compressed": row.compressed}


async def stage_policy_drill(args) -> None:
    name = "wattprint_audit_f"
    dsn = await create_scratch(name)
    old = (datetime(2025, 2, 1, tzinfo=UTC), datetime(2025, 2, 6, tzinfo=UTC))  # > 400 d old
    mid = (datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 4, tzinfo=UTC))
    recent = (datetime(2026, 10, 25, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))
    counts = await copy_slices(dsn, [old, mid, recent], with_estimates=False)
    eng = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    out: dict = {"copied_rows": counts, "run_at": datetime.now(UTC).isoformat(),
                 "slices": {"old": [str(x) for x in old], "mid": [str(x) for x in mid],
                            "recent": [str(x) for x in recent]}}
    async with eng.connect() as c:
        for a, b in (old, mid, recent):
            await backfill_aggregates(c, a, b)
        out["aggregate_rows_before_policies"] = {
            v: await c.scalar(text(f"SELECT count(*) FROM energy.reading_{v}"))
            for v in ("1m", "1h", "1d")}
        out["raw_chunks_before"] = await _chunk_state(c)
        mid_raw, recent_raw = await _raw_count(c, *mid), await _raw_count(c, *recent)
        await c.execute(text("SELECT ops.set_policies(true)"))
        # new jobs start immediately on the background scheduler: pause them all, run by hand
        await c.execute(text("SELECT alter_job(job_id, scheduled => false) "
                             "FROM timescaledb_information.jobs WHERE hypertable_name IS NOT NULL"))
        out["jobs_paused_for_deterministic_drill"] = True
        jobs = (await c.execute(text(
            "SELECT job_id, proc_name, hypertable_name, schedule_interval::text, config::text "
            "FROM timescaledb_information.jobs WHERE hypertable_name IS NOT NULL "
            "ORDER BY hypertable_name, proc_name"))).all()
        out["jobs_after_set_policies_true"] = [
            {"job_id": j[0], "proc": j[1], "hypertable": j[2], "schedule": j[3],
             "config": json.loads(j[4])} for j in jobs]
        await c.execute(text("CALL run_job(:j)"),
                        {"j": await _job(c, "policy_compression", "reading")})
        out["raw_chunks_after_compression_policy"] = await _chunk_state(c)
        old_raw = await _raw_count(c, *old)
        agg_before = await _view_counts(c, *old)
        mat_before = await _mat_counts(c, *old)
        await c.execute(text("CALL run_job(:j)"),
                        {"j": await _job(c, "policy_retention", "reading")})
        out["raw_chunks_after_raw_retention"] = await _chunk_state(c)
        old_info = {
            "raw_rows_before": old_raw, "raw_rows_after": await _raw_count(c, *old),
            "view_rows_before": agg_before, "materialized_rows_before": mat_before,
            "view_rows_after_raw_retention": await _view_counts(c, *old),
            "materialized_rows_after_raw_retention": await _mat_counts(c, *old),
        }
        refresh_jobs = {}
        for v in ("1m", "1h", "1d"):
            refresh_jobs[v] = await c.scalar(text(
                "SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = "
                "'policy_refresh_continuous_aggregate' AND hypertable_name = :t"),
                {"t": f"reading_{v}"})
        for v in ("1m", "1h", "1d"):
            await c.execute(text("CALL run_job(:j)"), {"j": refresh_jobs[v]})
        old_info["view_rows_after_refresh_policies"] = await _view_counts(c, *old)
        old_info["materialized_rows_after_refresh_policies"] = await _mat_counts(c, *old)
        out["refresh_policy_jobs_found"] = {k: v is not None for k, v in refresh_jobs.items()}
        # retention policy on the 1m aggregate (400 d): drops old materialization chunks
        r1m = await c.scalar(text(
            "SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = "
            "'policy_retention' AND hypertable_name = :t"), {"t": "reading_1m"})
        out["retention_policy_jobs"] = sorted(
            j["hypertable"] for j in out["jobs_after_set_policies_true"]
            if j["proc"] == "policy_retention")
        if r1m:
            await c.execute(text("CALL run_job(:j)"), {"j": r1m})
            old_info["materialized_rows_after_1m_retention_job"] = await _mat_counts(c, *old)
            old_info["view_rows_after_1m_retention_job"] = await _view_counts(c, *old)
        # a manual backfill over the dropped range
        await backfill_aggregates(c, *old)
        old_info["view_rows_after_backfill_over_dropped_range"] = await _view_counts(c, *old)
        old_info["materialized_rows_after_backfill_over_dropped_range"] = \
            await _mat_counts(c, *old)
        out["old_slice"] = old_info
        out["mid_slice_raw_rows_intact"] = await _raw_count(c, *mid) == mid_raw
        out["recent_slice_raw_rows_intact"] = await _raw_count(c, *recent) == recent_raw
    await eng.dispose()
    await drop_scratch(name)
    for k, v in out.items():
        results.record("policy_drill", k, v)
    log(f"policy drill: {json.dumps(out, default=str)[:1800]}")


# ------------------------------------------------------------------ I
def extrapolate(data: dict) -> dict:
    st = data["stats"]
    homes = 10_000
    home_years = st["home_years"]
    raw_bpr = st["bytes_per_reading_raw"]
    agg = st["bytes"]["aggregates"]
    one_m_bpr = agg["reading_1m"] / st["rows"]["aggregates"]["reading_1m"]
    small_per_home_year_10ch = (agg["reading_1h"] + agg["reading_1d"]) / home_years
    ratio = data.get("cagg_compression", {}).get("reading_1m", {}).get("ratio")
    est_bpr = st["bytes_per_device_estimate_raw"]
    measured_rate = data["load"]["house1"]["readings_per_s"]

    def scenario(channels: int, cadence_s: float, estimates: int = 0) -> dict:
        per_day = channels * 86400 / cadence_s
        raw_year = per_day * 365 * raw_bpr
        one_m_year = channels * 525_600 * one_m_bpr  # a 1 m row per channel per minute
        small_year = small_per_home_year_10ch * channels / 10
        est_year = estimates * 86400 / cadence_s * 365 * est_bpr
        unc = raw_year + one_m_year + small_year + est_year
        comp = raw_year + (one_m_year / ratio if ratio else one_m_year) + small_year + est_year
        return {
            "assumption": f"{channels} series per home, one reading per {cadence_s:g} s each"
                          + (f", {estimates} device_estimate series" if estimates else ""),
            "readings_per_home_day": round(per_day),
            "daily_ingest_rows_10k_homes": round(homes * per_day),
            "required_avg_rows_per_second": round(homes * per_day / 86400),
            "measured_single_stream_rows_per_second": measured_rate,
            "streams_needed_at_measured_rate": round(homes * per_day / 86400 / measured_rate, 2),
            "raw_gb_per_home_year": round(raw_year / 1e9, 4),
            "agg_1m_uncompressed_gb_per_home_year": round(one_m_year / 1e9, 4),
            "agg_1m_compressed_gb_per_home_year": round(one_m_year / ratio / 1e9, 4)
            if ratio else None,
            "agg_1h_1d_gb_per_home_year": round(small_year / 1e9, 5),
            "device_estimate_gb_per_home_year": round(est_year / 1e9, 4),
            "tb_per_year_10k_homes_1m_uncompressed": round(homes * unc / 1e12, 2),
            "tb_per_year_10k_homes_1m_compressed": round(homes * comp / 1e12, 2),
        }

    return {
        "measured_inputs": {
            "raw_bytes_per_reading_compressed": raw_bpr,
            "agg_1m_bytes_per_row_uncompressed": round(one_m_bpr, 1),
            "agg_1m_compression_ratio_scratch_measurement": ratio,
            "device_estimate_bytes_per_row": est_bpr,
        },
        "scenario_refit_like_10_series_7s": scenario(10, 7.0),
        "scenario_main_meter_only_1hz": scenario(1, 1.0),
        "scenario_main_plus_9_devices_30s_with_estimates": scenario(10, 30.0, 9),
        "assumptions": [
            "the spec states no sampling rate; three scenarios are shown",
            "REFIT: 10 series at about 7 s median cadence (measured)",
            "the 1 m aggregate has one row per series per minute that holds a sample; the "
            "scenarios assume every minute is covered (upper bound)",
            "1h/1d aggregate bytes are scaled from the measured 3-house size by series/10",
            "compressed raw size uses the measured 17x for all cadences (not measured for others)",
            "raw retention 13 months is NOT applied; figures are per year of ingest",
        ],
    }


async def stage_extrapolate(args) -> None:
    out = extrapolate(results.load())
    for k, v in out.items():
        results.record("extrapolation", k, v)
    log(json.dumps(out)[:1000])


# ------------------------------------------------------------------ H
def _run_module(db: str, results_file: Path, *argv: str) -> str:
    env = dict(os.environ)
    env["DATABASE_URL"] = make_url(scratch_url(db)).render_as_string(hide_password=False)
    env["AUDIT_RESULTS"] = str(results_file)
    proc = subprocess.run([sys.executable, "-m", "tests.audit.run", *argv], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{argv} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


async def stage_harness_check(args) -> None:
    """load (limited), backfill and compress end to end on a scratch DB with a temp results
    file: confirms the fixes of the two earlier harness bugs."""
    name = "wattprint_audit_h"
    await create_scratch(name)
    tmp = Path(tempfile.mkdtemp()) / "r.json"
    _run_module(name, tmp, "load", "--houses", "1", "--limit-rows", "200000")
    _run_module(name, tmp, "backfill")
    _run_module(name, tmp, "compress", "--workers", "2")
    data = results.load(tmp)
    views = {f"energy.{f}_{r}" for f in ("reading", "device_estimate") for r in ("1m", "1h", "1d")}
    timed = set(data["backfill"]["refresh_seconds_per_view"])
    st = data["compress"]["stats"]["reading"]
    dst = create_async_engine(scratch_url(name))
    async with dst.connect() as c:
        n_comp = await c.scalar(text(
            "SELECT count(*) FROM timescaledb_information.chunks WHERE "
            "hypertable_name='reading' AND hypertable_schema='energy' AND is_compressed"))
    await dst.dispose()
    out = {
        "scratch_db": name, "csv_rows_loaded": 200000,
        "backfill_timed_view_keys": sorted(timed),
        "backfill_keys_are_view_names": bool(timed) and timed <= views,
        "compress_stats_reading": st, "db_compressed_chunks": n_comp,
        "compressed_chunks_matches_db": st["compressed_chunks"] == n_comp,
        "ratio_is_number": isinstance(st["ratio_compressed_chunks"], int | float),
    }
    await drop_scratch(name)
    for k, v in out.items():
        results.record("harness_check", k, v)
    log(json.dumps(out, default=str)[:900])
    assert out["backfill_keys_are_view_names"] and out["compressed_chunks_matches_db"]
    assert out["ratio_is_number"]


# ------------------------------------------------------------------ D (cause of the 1d backfill cost)
async def stage_refresh_cost_scratch(args) -> None:
    """Backfill 30 days with and without 4 months of newer, not yet materialized raw data."""
    from tests.audit.part_b import trim_plan

    name = "wattprint_audit_d"
    a = (datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 5, 31, tzinfo=UTC))
    later = (datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    out: dict = {}
    for label, slices, mat_only in (
        ("window_only", [a], False),
        ("window_plus_newer_unmaterialized_raw", [a, later], False),
        ("window_plus_newer_raw_with_1m_and_1h_materialized_only", [a, later], True),
    ):
        dsn = await create_scratch(name)
        counts = await copy_slices(dsn, slices, with_estimates=False)
        eng = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
        if mat_only:
            async with eng.connect() as c0:
                for v in ("reading_1m", "reading_1h"):
                    await c0.execute(text(
                        f"ALTER MATERIALIZED VIEW energy.{v} SET (timescaledb.materialized_only = true)"))
        per_view = await timed_backfill(eng, *a)
        async with eng.connect() as c:
            await c.execute(text("SET work_mem = '256MB'"))
            q = ("SELECT time_bucket('1 day', bucket, 'Asia/Ho_Chi_Minh') b, series_id, "
                 "sum(avg_w * n) / sum(n), sum(n), sum(energy_wh), sum(covered_minutes) "
                 "FROM energy.reading_1h WHERE bucket >= '2026-05-01 17:00+00' "
                 "AND bucket < '2026-05-31 17:00+00' GROUP BY 1, 2")
            raw = (await c.get_raw_connection()).driver_connection
            rows = await raw.fetch("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + q)
            plan = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
        await eng.dispose()
        out[label] = {"copied_rows": counts, "backfill_seconds_per_view": per_view,
                      "plan_of_1d_source_query_over_reading_1h": trim_plan(plan)}
        log(f"{label}: {per_view}")
    await drop_scratch(name)
    results.record("refresh_cost", "scratch_comparison", out)
