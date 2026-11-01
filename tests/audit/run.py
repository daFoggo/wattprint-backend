"""Audit stages: python -m tests.audit.run <stage> [options]

Order (spec section 9): env, policies off, load, estimates, backfill, `pytest -m audit`
(idempotency + energy vs exact), compress, `pytest -m audit` again, stats, report.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import event, text

from app.services.aggregates import backfill_aggregates
from tests.audit import part_b, part_b2, results
from tests.audit.support import database_name, ensure_database, guard, make_engine

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("REFIT_DIR", "/data/CLEAN_REFIT_081116"))
BEGIN, END = "<!-- audit:begin -->", "<!-- audit:end -->"
# TimescaleDB's own maintenance jobs (telemetry, job-stat retention) have no hypertable
POLICY_JOBS = "proc_name LIKE 'policy\\_%' AND hypertable_name IS NOT NULL"
FAMILIES = ("reading", "device_estimate")
RESOLUTIONS = ("1m", "1h", "1d")


def log(msg: str) -> None:
    print(f"[{datetime.now(UTC):%H:%M:%S}] {msg}", flush=True)


def csv_path(house: int) -> Path:
    return DATA_DIR / f"CLEAN_House{house}.csv"


def last_unix(csv: Path) -> int:
    """Unix column of the last non-empty line, read from the file tail only."""
    size = csv.stat().st_size
    with open(csv, "rb") as f:
        f.seek(max(0, size - 8192))
        lines = [ln for ln in f.read().decode("utf-8", "replace").splitlines() if ln.strip()]
    return int(lines[-1].split(",")[1])


def shift_days_for_csv(csv: Path, today: date | None = None) -> int:
    """Whole-day shift that moves the CSV's last reading onto yesterday's UTC date."""
    today = today or datetime.now(UTC).date()
    last_date = datetime.fromtimestamp(last_unix(csv), UTC).date()
    return (today - timedelta(days=1) - last_date).days


def parse_houses(arg: str) -> list[int]:
    return [int(x) for x in arg.split(",") if x]


# ------------------------------------------------------------------ env / policies
async def stage_env(args) -> None:
    eng = make_engine()
    async with eng.connect() as c:
        pg = {
            "version": await c.scalar(text("SHOW server_version")),
            "timescaledb": await c.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
            ),
        }
        for k in ("shared_buffers", "max_wal_size", "effective_cache_size", "work_mem",
                  "maintenance_work_mem", "checkpoint_timeout", "max_connections",
                  "wal_compression", "synchronous_commit", "fsync"):
            pg[k] = await c.scalar(text(f"SHOW {k}"))
    await eng.dispose()
    mem_kb = int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1))
    sizes = {f"house{h}": csv_path(h).stat().st_size for h in range(1, 22) if csv_path(h).exists()}
    results.record("env", "cpus", os.cpu_count())
    results.record("env", "memory_mb_visible", mem_kb // 1024)
    results.record("env", "postgres", pg)
    results.record("env", "refit_csv_bytes", sizes)
    disk = shutil.disk_usage("/")
    results.record("env", "docker_vm_disk_bytes", {"total": disk.total, "free": disk.free})
    results.record("env", "recorded_at", datetime.now(UTC).isoformat())
    log(f"env recorded: cpus={os.cpu_count()} mem={mem_kb // 1024} MB pg={pg['version']}")


async def stage_policies_off(args) -> None:
    await ensure_database()
    eng = make_engine(isolation_level="AUTOCOMMIT")
    async with eng.connect() as c:
        await c.execute(text("SELECT ops.set_policies(false)"))
        left = (
            await c.execute(
                text(
                    "SELECT job_id, proc_name, hypertable_name "
                    f"FROM timescaledb_information.jobs WHERE {POLICY_JOBS}"
                )
            )
        ).all()
    await eng.dispose()
    if left:
        raise SystemExit(f"policy jobs remain after set_policies(false): {left}")
    results.record("policies", "state", "off")
    results.record("policies", "jobs_remaining", 0)
    log("policies off, no policy jobs remain")


# ------------------------------------------------------------------ load
async def _run_loader(house: int, shift: int, tag: str, limit_rows: int | None = None) -> dict:
    cmd = [sys.executable, "-m", "app.cli.load_refit", "--house", str(house),
           "--shift-days", str(shift)]
    if limit_rows:
        cmd += ["--limit-rows", str(limit_rows)]
    started = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out = (await proc.communicate())[0].decode()
    wall = time.perf_counter() - started
    log(f"{tag} house {house} exit={proc.returncode}: {out.strip().splitlines()[-1:]}")
    if proc.returncode != 0:
        raise SystemExit(f"load house {house} failed:\n{out}")
    m = re.search(r"rows_in=(\d+) rows_new=(\d+) rows_dup=(\d+) rows_bad=(\d+) in ([\d.]+)s", out)
    rows_in, rows_new, rows_dup, rows_bad = (int(m.group(i)) for i in range(1, 5))
    secs = float(m.group(5))
    return {
        "shift_days": shift, "rows_in": rows_in, "rows_new": rows_new, "rows_dup": rows_dup,
        "rows_bad": rows_bad, "csv_rows": rows_in // 10, "load_seconds": round(secs, 1),
        "process_wall_seconds": round(wall, 1), "readings_per_s": round(rows_in / secs),
    }


async def stage_load(args) -> None:
    await ensure_database()
    houses = parse_houses(args.houses)
    prior = results.load().get("load", {})
    todo = [h for h in houses if args.force or f"house{h}" not in prior]
    for h in houses:
        if h not in todo:
            log(f"house {h} already loaded (use --force to reload)")
    shifts = {h: shift_days_for_csv(csv_path(h)) for h in todo}
    for h, s in shifts.items():
        last = datetime.fromtimestamp(last_unix(csv_path(h)), UTC) + timedelta(days=s)
        log(f"house {h}: shift {s} days, last reading -> {last:%F %T} UTC")
    started = time.perf_counter()
    if args.parallel:
        out = await asyncio.gather(
            *(_run_loader(h, shifts[h], "par", args.limit_rows) for h in todo)
        )
    else:
        out = [await _run_loader(h, shifts[h], "seq", args.limit_rows) for h in todo]
    wall = time.perf_counter() - started
    for h, r in zip(todo, out, strict=True):
        results.record("load", f"house{h}", r)
    if todo:
        total = sum(r["rows_in"] for r in out)
        mode = "parallel" if args.parallel else "sequential"
        batch = {
            "houses": todo, "mode": mode, "wall_seconds": round(wall, 1), "readings": total,
            "aggregate_readings_per_s": round(total / wall),
            "mean_per_stream_readings_per_s": round(
                sum(r["readings_per_s"] for r in out) / len(out)
            ),
        }
        results.record("load", f"run_{mode}_{'-'.join(map(str, todo))}", batch)
        log(f"load done: {batch}")


# ------------------------------------------------------------------ estimates
async def stage_estimates(args) -> None:
    await ensure_database()
    houses = parse_houses(args.houses)
    eng = make_engine()
    t0 = time.perf_counter()
    totals: dict = {"series_created": 0, "rows_inserted": 0, "per_house": {}}
    async with eng.connect() as c:
        await c.execute(text("SET work_mem = '256MB'"))
        for h in houses:
            home_id = await c.scalar(
                text("SELECT id FROM core.home WHERE name = :n"), {"n": f"REFIT House {h}"}
            )
            if home_id is None:
                raise SystemExit(f"house {h} not provisioned")
            plugs = (
                await c.execute(
                    text("SELECT series_id, device_id FROM energy.series "
                         "WHERE home_id=:h AND kind='plug' ORDER BY series_id"),
                    {"h": home_id},
                )
            ).all()
            run_id = await c.scalar(
                text("SELECT run_id FROM energy.inference_run "
                     "WHERE home_id=:h AND model_name='audit-standin' ORDER BY run_id LIMIT 1"),
                {"h": home_id},
            )
            if run_id is None:
                run_id = await c.scalar(
                    text("INSERT INTO energy.inference_run (home_id, model_name, model_version, "
                         "window_start, window_end, status) "
                         "SELECT :h, 'audit-standin', 'plug-copy', min(ts), max(ts), 'running' "
                         "FROM energy.reading WHERE series_id = ANY(:ids) RETURNING run_id"),
                    {"h": home_id, "ids": [p.series_id for p in plugs]},
                )
                await c.commit()
            n_house = 0
            for p in plugs:
                dev_series = await c.scalar(
                    text("INSERT INTO energy.series (home_id, kind, device_id, metric, unit) "
                         "VALUES (:h, 'device', :d, 'power_w', 'W') "
                         "ON CONFLICT ON CONSTRAINT uq_series_home_kind_device_metric "
                         "DO UPDATE SET unit = EXCLUDED.unit RETURNING series_id"),
                    {"h": home_id, "d": p.device_id},
                )
                have = await c.scalar(
                    text("SELECT count(*) FROM energy.device_estimate WHERE series_id = :s"),
                    {"s": dev_series},
                )
                if have:
                    log(f"house {h} plug {p.series_id}->{dev_series}: {have} rows exist, skipped")
                    n_house += have
                    await c.commit()
                    continue
                t1 = time.perf_counter()
                res = await c.execute(
                    text("INSERT INTO energy.device_estimate (ts, series_id, value, run_id) "
                         "SELECT ts, :ds, value, :run FROM energy.reading WHERE series_id = :ps "
                         "ON CONFLICT (series_id, ts) DO UPDATE SET value = EXCLUDED.value, "
                         "run_id = EXCLUDED.run_id"),
                    {"ds": dev_series, "ps": p.series_id, "run": run_id},
                )
                await c.commit()
                totals["series_created"] += 1
                n_house += res.rowcount
                log(f"house {h} plug {p.series_id}->{dev_series}: {res.rowcount} rows "
                    f"in {time.perf_counter() - t1:.1f}s")
            await c.execute(
                text("UPDATE energy.inference_run SET status='ok', finished_at=now() "
                     "WHERE run_id=:r"),
                {"r": run_id},
            )
            await c.commit()
            totals["per_house"][f"house{h}"] = n_house
            totals["rows_inserted"] += n_house
    await eng.dispose()
    totals["duration_seconds"] = round(time.perf_counter() - t0, 1)
    for k, v in totals.items():
        results.record("estimates", k, v)
    log(f"estimates done: {totals}")


# ------------------------------------------------------------------ backfill
async def _hypertable_range(c, name: str) -> tuple[datetime, datetime]:
    row = (
        await c.execute(
            text("SELECT min(range_start), max(range_end) FROM timescaledb_information.chunks "
                 "WHERE hypertable_schema='energy' AND hypertable_name=:n"),
            {"n": name},
        )
    ).one()
    return row[0], row[1]


async def stage_backfill(args) -> None:
    await ensure_database()
    eng = make_engine(isolation_level="AUTOCOMMIT")
    timings: dict[str, float] = {}
    windows: list[dict] = []

    @event.listens_for(eng.sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        if "refresh_continuous_aggregate" in statement:
            context._audit_t0 = time.perf_counter()

    @event.listens_for(eng.sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        if "refresh_continuous_aggregate" in statement:
            view = parameters["v"] if isinstance(parameters, dict) else parameters[0]
            timings[view] = timings.get(view, 0.0) + time.perf_counter() - context._audit_t0

    skipped_all: list[tuple[str, str, str]] = []
    t0 = time.perf_counter()
    async with eng.connect() as c:
        ranges = [r for r in (await _hypertable_range(c, "reading"),
                              await _hypertable_range(c, "device_estimate")) if r[0] is not None]
        lo, hi = min(r[0] for r in ranges), max(r[1] for r in ranges)
        log(f"backfill range {lo:%F} .. {hi:%F}")
        start = lo
        while start < hi:
            end = min(start + timedelta(days=30), hi)
            w0 = time.perf_counter()
            skipped = await backfill_aggregates(c, start, end)
            skipped_all += [(w.view, w.from_ts.isoformat(), w.to_ts.isoformat()) for w in skipped]
            windows.append({"from": start.isoformat(), "to": end.isoformat(),
                            "seconds": round(time.perf_counter() - w0, 1)})
            log(f"window {start:%F}..{end:%F} {windows[-1]['seconds']}s")
            start = end
        counts = {}
        for fam in FAMILIES:
            for res in RESOLUTIONS:
                counts[f"energy.{fam}_{res}"] = await c.scalar(
                    text(f"SELECT count(*) FROM energy.{fam}_{res}")
                )
    await eng.dispose()
    results.record("backfill", "range", [lo.isoformat(), hi.isoformat()])
    results.record("backfill", "total_seconds", round(time.perf_counter() - t0, 1))
    results.record("backfill", "refresh_seconds_per_view",
                   {k: round(v, 1) for k, v in sorted(timings.items())})
    results.record("backfill", "windows", windows)
    results.record("backfill", "skipped_windows", skipped_all)  # [] for a fresh load
    if skipped_all:
        log(f"WARNING: backfill skipped {len(skipped_all)} windows (raw rows missing)")
    results.record("backfill", "aggregate_rows", counts)
    log(f"backfill done in {time.perf_counter() - t0:.0f}s: {counts}")


# ------------------------------------------------------------------ compress / stats
async def _compress_one(eng, chunk: str, sem) -> None:
    async with sem, eng.connect() as c:
        await c.execute(
            text("SELECT compress_chunk(CAST(:c AS regclass), if_not_compressed => true)"),
            {"c": chunk},
        )


async def _sizes(c) -> dict:
    out = {}
    for t in FAMILIES:
        out[t] = int(
            await c.scalar(text("SELECT hypertable_size(CAST(:t AS regclass))"),
                           {"t": f"energy.{t}"})
        )
    return out


async def stage_compress(args) -> None:
    await ensure_database()
    eng = make_engine(isolation_level="AUTOCOMMIT")
    sem = asyncio.Semaphore(args.workers)
    t0 = time.perf_counter()
    async with eng.connect() as c:
        before = await _sizes(c)
        chunks = {}
        for t in FAMILIES:
            rows = await c.execute(
                text("SELECT format('%I.%I', chunk_schema, chunk_name) "
                     "FROM timescaledb_information.chunks "
                     "WHERE hypertable_schema='energy' AND hypertable_name=:t "
                     "AND NOT is_compressed AND range_end < now() - interval '2 days' "
                     "ORDER BY range_start"),
                {"t": t},
            )
            chunks[t] = [r[0] for r in rows]
    log(f"compressing {sum(map(len, chunks.values()))} chunks, {args.workers} workers; "
        f"before={before}")
    done = 0
    for names in chunks.values():
        tasks = [asyncio.create_task(_compress_one(eng, n, sem)) for n in names]
        for fut in asyncio.as_completed(tasks):
            await fut
            done += 1
            if done % 25 == 0:
                log(f"  compressed {done}")
    stats = {}
    async with eng.connect() as c:
        after = await _sizes(c)
        for t in FAMILIES:
            r = (
                await c.execute(
                    text("SELECT total_chunks, number_compressed_chunks, "
                         "before_compression_total_bytes AS b, after_compression_total_bytes AS a "
                         "FROM hypertable_compression_stats(CAST(:t AS regclass))"),
                    {"t": f"energy.{t}"},
                )
            ).first()  # no row at all when the hypertable has no compressed chunk
            if r is None:
                stats[t] = {"compressed_chunks": 0, "total_chunks": 0,
                            "compressed_before_bytes": 0, "compressed_after_bytes": 0,
                            "ratio_compressed_chunks": None}
                continue
            stats[t] = {
                "compressed_chunks": int(r.number_compressed_chunks),
                "total_chunks": int(r.total_chunks),
                "compressed_before_bytes": int(r.b or 0),
                "compressed_after_bytes": int(r.a or 0),
                "ratio_compressed_chunks": round(float(r.b) / float(r.a), 2) if r.a else None,
            }
    await eng.dispose()
    results.record("compress", "hypertable_size_before_bytes", before)
    results.record("compress", "hypertable_size_after_bytes", after)
    results.record("compress", "stats", stats)
    results.record("compress", "ratio_hypertable_size",
                   {t: round(before[t] / after[t], 2) for t in before if after[t]})
    results.record("compress", "chunks_compressed_this_run", done)
    results.record("compress", "duration_seconds", round(time.perf_counter() - t0, 1))
    results.record("compress", "workers", args.workers)
    log(f"compress done in {time.perf_counter() - t0:.0f}s: {stats}")


async def stage_stats(args) -> None:
    await ensure_database()
    eng = make_engine()
    async with eng.connect() as c:
        sizes = await _sizes(c)
        agg = {}
        views = (
            await c.execute(
                text("SELECT view_name, format('%I.%I', materialization_hypertable_schema, "
                     "materialization_hypertable_name) AS mat "
                     "FROM timescaledb_information.continuous_aggregates "
                     "WHERE view_schema='energy' ORDER BY 1")
            )
        ).all()
        for v in views:
            agg[v.view_name] = int(
                await c.scalar(text("SELECT hypertable_size(CAST(:m AS regclass))"), {"m": v.mat})
            )
        n_reading = int(await c.scalar(text("SELECT count(*) FROM energy.reading")))
        n_est = int(await c.scalar(text("SELECT count(*) FROM energy.device_estimate")))
        rows_agg = {
            v.view_name: int(await c.scalar(text(f"SELECT count(*) FROM energy.{v.view_name}")))
            for v in views
        }
        homes = (
            await c.execute(
                text("SELECT h.name, s.series_id FROM energy.series s "
                     "JOIN core.home h ON h.id = s.home_id WHERE s.kind='main' ORDER BY h.name")
            )
        ).all()
        spans = {}
        for h in homes:
            lo, hi = (
                await c.execute(
                    text("SELECT min(ts), max(ts) FROM energy.reading WHERE series_id=:s"),
                    {"s": h.series_id},
                )
            ).one()
            if lo is not None:
                spans[h.name] = (hi - lo).total_seconds() / 86400
    await eng.dispose()
    home_years = sum(spans.values()) / 365.25
    reading_aggs = sum(v for k, v in agg.items() if k.startswith("reading_"))
    raw_plus_agg = sizes["reading"] + reading_aggs
    out = {
        "bytes": {**sizes, "aggregates": agg, "aggregates_total": sum(agg.values())},
        "rows": {"reading": n_reading, "device_estimate": n_est, "aggregates": rows_agg},
        "bytes_per_reading_raw": round(sizes["reading"] / n_reading, 3) if n_reading else None,
        "bytes_per_device_estimate_raw":
            round(sizes["device_estimate"] / n_est, 3) if n_est else None,
        "bytes_per_reading_incl_reading_aggregates":
            round(raw_plus_agg / n_reading, 3) if n_reading else None,
        "home_days_of_data": {k: round(v, 1) for k, v in spans.items()},
        "home_years": round(home_years, 3),
        "bytes_per_home_year_reading_plus_aggregates":
            round(raw_plus_agg / home_years) if home_years else None,
        "total_database_bytes": sizes["reading"] + sizes["device_estimate"] + sum(agg.values()),
    }
    for k, v in out.items():
        results.record("stats", k, v)
    log("stats: " + json.dumps(out, default=str)[:700])


# ------------------------------------------------------------------ worked examples
EXAMPLE_SQL = text(
    "WITH a AS (SELECT ts, value, quality,"
    "  extract(epoch FROM lead(ts) OVER (ORDER BY ts) - ts) AS gap FROM energy.reading"
    "  WHERE series_id = :sid AND ts >= :d AND ts < :d + interval '1 day' + interval '1 minute'),"
    " b AS (SELECT ts, value, extract(epoch FROM lead(ts) OVER (ORDER BY ts) - ts) AS gap"
    "  FROM energy.reading WHERE series_id = :sid AND ts >= :d"
    "  AND ts < :d + interval '1 day' + interval '1 minute' AND quality & 1 = 0),"
    " day AS (SELECT * FROM a WHERE ts < :d + interval '1 day')"
    " SELECT"
    " (SELECT sum(value * least(gap, 35)) FILTER (WHERE quality & 1 = 0) / 3600 FROM day"
    "   WHERE gap IS NOT NULL) AS reference_wh,"
    " (SELECT sum(value * least(gap, 35)) / 3600 FROM b WHERE gap IS NOT NULL"
    "   AND ts < :d + interval '1 day') AS hold_across_flagged_wh,"
    " (SELECT sum(value * least(gap, 120)) / 3600 FROM b WHERE gap IS NOT NULL"
    "   AND ts < :d + interval '1 day') AS hold_across_flagged_cap_120s_wh,"
    " (SELECT energy_wh FROM energy.reading_1d WHERE series_id = :sid AND bucket = :d) AS view_wh,"
    " (SELECT covered_minutes FROM energy.reading_1d WHERE series_id = :sid AND bucket = :d)"
    "   AS covered_minutes,"
    " (SELECT count(*) FROM day) AS samples,"
    " (SELECT count(*) FROM day WHERE quality & 1 = 1) AS flagged_samples,"
    " (SELECT count(*) FROM day WHERE gap > 35) AS intervals_over_35s,"
    " (SELECT count(*) FROM day WHERE gap > 120) AS intervals_over_120s,"
    " (SELECT max(gap) FROM day) AS max_gap_s"
)
# (day start UTC, label, cause). Numbers are generated; the cause text is written by hand.
EXAMPLE_DAYS = (
    ("2025-11-22T17:00:00+00:00", "worst day", "irregular cadence: about 62 s logging vs the "
     "35 s cap (reference) while the view counts a full minute per minute with a sample"),
    ("2025-08-24T17:00:00+00:00", "flagged samples only",
     "Issues-flagged samples are missing time in the reference, covered in the view"),
    ("2025-04-17T17:00:00+00:00", "flagged plus one gap",
     "flagged samples plus one 194 s gap"),
    ("2025-08-25T17:00:00+00:00", "control (passes)",
     "gaps agree between reference and view"),
)


async def stage_examples(args) -> None:
    """Worked examples for house 1 (read-only) and the gate baseline from the first measurement."""
    await ensure_database()
    eng = make_engine()
    out = []
    async with eng.connect() as c:
        sid = await c.scalar(
            text("SELECT s.series_id FROM energy.series s JOIN core.home h ON h.id = s.home_id "
                 "WHERE h.name = 'REFIT House 1' AND s.kind = 'main'")
        )
        await c.execute(text("SET work_mem = '256MB'"))
        for day, label, cause in EXAMPLE_DAYS:
            d = datetime.fromisoformat(day)
            row = (await c.execute(EXAMPLE_SQL, {"sid": sid, "d": d})).one()._asdict()
            row = {k: (float(v) if v is not None else None) for k, v in row.items()}
            row["err_pct"] = (row["view_wh"] - row["reference_wh"]) / row["reference_wh"] * 100
            out.append({"day_start_utc": day, "label": label, "cause_source": "manual",
                        "cause": cause, **row})
            log(f"example {day}: reference {row['reference_wh']:.1f} view {row['view_wh']:.1f}")
    await eng.dispose()
    results.record("energy_examples", "house1_days", out)
    data = results.load()
    if "energy_gate_baseline" not in data:
        pre = data["energy_vs_exact_pre_compress"]
        for house, v in pre.items():
            results.record("energy_gate_baseline", house, {
                "days_over_gate": v["full_coverage"]["days_over_gate"],
                "err_pct_max": v["full_coverage"]["err_pct_max"],
                "source": "first measurement, pre-compression"})


# ------------------------------------------------------------------ report
def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4g}" if abs(v) < 1000 else f"{v:,.0f}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v)


def _flatten(prefix: str, v, out: list[tuple[str, str]]) -> None:
    if isinstance(v, dict):
        for k in sorted(v):
            _flatten(f"{prefix}.{k}" if prefix else k, v[k], out)
    elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
        for i, x in enumerate(v):
            _flatten(f"{prefix}[{i}]", x, out)
    elif isinstance(v, list):
        out.append((prefix, ", ".join(_fmt(x) for x in v)))
    else:
        out.append((prefix, _fmt(v)))


# per-day samples, per-window timings, worst-day lists and plan details stay in the JSON only
NOISY = re.compile(
    r"(^|\.)worst\[|^days\.|^windows\[|\.plans\[|plan_of_|query_plan|"
    r"^jobs_after_set_policies_true|^refit_csv_bytes"
)


def render(data: dict) -> str:
    lines = ["## Measured results", "",
             "Generated by `python -m tests.audit.run report` from `docs/audit-results.json`; "
             "do not edit this block by hand.", ""]
    for stage in sorted(data):
        rows: list[tuple[str, str]] = []
        _flatten("", data[stage], rows)
        rows = [(k, v) for k, v in rows if not NOISY.search(k)]
        lines += [f"### {stage}", "", "| key | value |", "|---|---|"]
        lines += [f"| `{k}` | {v} |" for k, v in rows]
        lines.append("")
    return "\n".join(lines)


def update_report(doc: str, block: str) -> str:
    body = f"{BEGIN}\n{block}\n{END}"
    if BEGIN in doc and END in doc:
        head, rest = doc.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        return head + body + tail
    return doc.rstrip("\n") + "\n\n" + body + "\n"


async def stage_report(args) -> None:
    path = ROOT / "docs" / "database-audit.md"
    doc = path.read_text(encoding="utf-8")
    path.write_text(update_report(doc, render(results.load())), encoding="utf-8")
    log(f"report written to {path}")


STAGES = {
    "env": stage_env, "policies": stage_policies_off, "load": stage_load,
    "estimates": stage_estimates, "backfill": stage_backfill, "compress": stage_compress,
    "stats": stage_stats, "examples": stage_examples, "report": stage_report,
    "latency": part_b.stage_latency, "refresh-cost": part_b.stage_refresh_cost,
    "refresh-cost-scratch": part_b2.stage_refresh_cost_scratch,
    "cagg-compression": part_b2.stage_cagg_compression,
    "policy-drill": part_b2.stage_policy_drill, "extrapolate": part_b2.stage_extrapolate,
    "harness-check": part_b2.stage_harness_check,
}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tests.audit.run")
    p.add_argument("stage", choices=sorted(STAGES))
    p.add_argument("mode", nargs="?", help="'off' for the policies stage")
    p.add_argument("--houses", default="1,2,3")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit-rows", type=int)
    p.add_argument("--cold", action="store_true")
    args = p.parse_args(argv)
    if args.stage == "policies" and args.mode != "off":
        p.error("usage: policies off")
    if args.stage != "report":
        guard()
    log(f"stage {args.stage} on database {database_name()}")
    asyncio.run(STAGES[args.stage](args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
