"""Audit part B stages: latency, refresh cost, cagg compression, policy drill, extrapolation,
harness check.  Registered in tests/audit/run.py; numbers go to docs/audit-results.json.
"""

# ruff: noqa: E501 - dense audit scripts with long SQL strings

import json
import re
import statistics
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.services.bill import compute_bill
from app.modules.energy.services.meter import (
    device_breakdown,
    latest_power,
    meter_series,
    pick_step,
)
from tests.audit import results
from tests.audit.support import make_engine

ROOT = Path(__file__).resolve().parents[2]
N_RUNS = 30


def log(msg: str) -> None:
    print(f"[{datetime.now(UTC):%H:%M:%S}] {msg}", flush=True)


def summarize_ms(samples: list[float]) -> dict:
    s = sorted(samples)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    return {
        "n": len(s),
        "p50_ms": round(statistics.median(s), 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(s[-1], 2),
    }


# ------------------------------------------------------------------ EXPLAIN capture
def _walk(node: dict, acc: dict) -> None:
    rel = node.get("Relation Name")
    if rel:
        acc["relations"][rel] = acc["relations"].get(rel, 0) + 1
    t = node["Node Type"]
    acc["nodes"][t] = acc["nodes"].get(t, 0) + 1
    for k in ("Subplans Removed",):
        if k in node:
            acc["subplans_removed"] = acc.get("subplans_removed", 0) + node[k]
    for child in node.get("Plans", []):
        _walk(child, acc)


def trim_plan(plan_json: list) -> dict:
    top = plan_json[0]
    root = top["Plan"]
    acc: dict = {"relations": {}, "nodes": {}}
    _walk(root, acc)
    chunks = [r for r in acc["relations"] if r.startswith("_hyper_") or r.startswith("compress_")]
    return {
        "execution_ms": round(top["Execution Time"], 2),
        "planning_ms": round(top["Planning Time"], 2),
        "root_rows": root.get("Actual Rows"),
        "shared_hit": root.get("Shared Hit Blocks"),
        "shared_read": root.get("Shared Read Blocks"),
        "relations_scanned": len(acc["relations"]),
        "chunk_relations_scanned": len(chunks),
        "node_counts": dict(sorted(acc["nodes"].items(), key=lambda kv: -kv[1])[:8]),
        "subplans_removed": acc.get("subplans_removed", 0),
    }


class Capture:
    """Collects (statement, parameters) of the SELECTs a service call runs on an engine."""

    def __init__(self, engine):
        self.items: list[tuple[str, tuple]] = []
        self._on = False
        event.listen(engine.sync_engine, "before_cursor_execute", self._hook)

    def _hook(self, conn, cursor, statement, parameters, context, executemany):
        if self._on and statement.lstrip().upper().startswith(("SELECT", "WITH")):
            self.items.append((statement, tuple(parameters) if parameters else ()))

    def start(self):
        self.items.clear()
        self._on = True

    def stop(self):
        self._on = False
        return list(self.items)


async def explain(
    session: AsyncSession, statements: list[tuple[str, tuple]], only_energy: bool = True
) -> list[dict]:
    out = []
    raw = (await (await session.connection()).get_raw_connection()).driver_connection
    for stmt, params in statements:
        if only_energy and "public." not in stmt:
            continue
        rows = await raw.fetch("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + stmt, *params)
        plan = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
        out.append({"sql": re.sub(r"\s+", " ", stmt)[:160], **trim_plan(plan)})
    return out


# ------------------------------------------------------------------ latency
async def _setup_homes(engine) -> dict:
    async with engine.connect() as c:
        rows = (
            await c.execute(
                text(
                    "SELECT h.id AS home, h.name, s.series_id FROM public.tb_home h JOIN public.tb_series s "
                    "ON s.home_id = h.id AND s.kind = 'main' WHERE h.name LIKE 'REFIT House %' "
                    "ORDER BY h.name"
                )
            )
        ).all()
        homes = {}
        for r in rows:
            end = await c.scalar(
                text("SELECT max(ts) FROM public.tb_reading WHERE series_id = :s"),
                {"s": r.series_id},
            )
            homes[r.name] = {"home": r.home, "series": r.series_id, "end": end}
        return homes


def _cases(homes: dict):
    """name -> (expected step or None, factory(i, session) -> awaitable)."""
    names = sorted(homes)

    def pick(i):
        h = homes[names[i % len(names)]]
        return h["home"], h["end"] - timedelta(hours=(i * 157) % 9000)  # up to ~375 days back

    def series_case(points, span_days, step):
        async def run(i, s):
            home, until = pick(i)
            since = until - timedelta(days=span_days)
            assert pick_step(since, until, points) == step
            return await meter_series(
                s, home, since, until, points, now=until + timedelta(minutes=1)
            )

        return step, run

    async def latest(i, s):
        home, until = pick(i)
        return await latest_power(s, home, now=until + timedelta(minutes=1))

    async def devices(i, s, days=1):
        home, until = pick(i)
        return await device_breakdown(s, home, until - timedelta(days=days), until)

    async def devices30(i, s):
        return await devices(i, s, 30)

    async def bill(i, s):
        home, _ = pick(i)
        k = i % 16  # months 2025-06 .. 2026-09 (tariff versions start 2025-05-10)
        period = date(2025 + (5 + k) // 12, (5 + k) % 12 + 1, 1)
        res = await compute_bill(s, home, period, now=datetime(2026, 11, 1, tzinfo=UTC))
        await s.rollback()  # do not persist audit bills
        return res

    return {
        "series_1d_over_90d": series_case(90, 90, "1d"),
        "series_6h_over_90d": series_case(360, 90, "6h"),
        "series_1h_over_45d": series_case(1080, 45, "1h"),
        "series_5m_over_1d": series_case(288, 1, "5m"),
        "series_week_15m_over_7d": series_case(2000, 7, "15m"),
        "latest_power": (None, latest),
        "device_breakdown_1d_hourly": (None, devices),
        "device_breakdown_30d_daily": (None, devices30),
        "compute_bill_month": (None, bill),
    }


async def _measure(engine, factory, varied: bool) -> list[float]:
    times = []
    for i in range(N_RUNS + (0 if varied else 1)):
        async with AsyncSession(engine, expire_on_commit=False) as s:
            t0 = time.perf_counter()
            await factory(i if varied else 0, s)
            dt = (time.perf_counter() - t0) * 1000
        if varied or i > 0:  # warm: first call is the warm-up
            times.append(dt)
    return times


async def stage_latency_cold(eng, homes) -> None:
    """First calls after a server restart (empty shared_buffers; OS cache may stay warm)."""
    out = {}
    for name, (_step, factory) in _cases(homes).items():
        ms = []
        for i in range(5):
            async with AsyncSession(eng, expire_on_commit=False) as s:
                t0 = time.perf_counter()
                await factory(i, s)
                ms.append(round((time.perf_counter() - t0) * 1000, 1))
        out[name] = {"first_calls_ms": ms, "first_call_ms": ms[0]}
        log(f"cold {name}: {ms}")
    results.record("latency", "cold_after_restart", out)


async def stage_latency(args) -> None:
    eng = make_engine(pool_size=2)
    cap = Capture(eng)
    homes = await _setup_homes(eng)
    if getattr(args, "cold", False):
        await stage_latency_cold(eng, homes)
        await eng.dispose()
        return
    out: dict = {"runs_per_case": N_RUNS}
    async with eng.connect() as c:
        out["compressed_chunks_reading"] = await c.scalar(
            text(
                "SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name='tb_reading' "
                "AND hypertable_schema = 'public' AND is_compressed"
            )
        )
    for name, (_step, factory) in _cases(homes).items():
        warm = await _measure(eng, factory, varied=False)
        varied = await _measure(eng, factory, varied=True)
        async with AsyncSession(eng, expire_on_commit=False) as s:
            cap.start()
            await factory(5, s)
            stmts = cap.stop()
            plans = await explain(s, stmts, only_energy=name != "compute_bill_month")
        target = 20.0 if name == "latest_power" else 100.0
        out[name] = {
            "warm": summarize_ms(warm),
            "varied_windows": summarize_ms(varied),
            "target_p95_ms": target,
            "pass": summarize_ms(warm)["p95_ms"] <= target
            and summarize_ms(varied)["p95_ms"] <= target,
            "plans": plans,
        }
        log(f"{name}: warm {out[name]['warm']} varied {out[name]['varied_windows']}")
    results.record("latency", "settled_data", out)
    await _latency_tail(eng, cap, homes)
    await eng.dispose()


async def _watermark(c, view: str) -> datetime:
    return await c.scalar(
        text(
            "SELECT _timescaledb_functions.to_timestamp(_timescaledb_functions.cagg_watermark("
            "(SELECT mat_hypertable_id FROM _timescaledb_catalog.continuous_agg "
            "WHERE user_view_schema = 'public' AND user_view_name = :v)))"
        ),
        {"v": view},
    )


async def _latency_tail(eng, cap, homes) -> None:
    """Lagging watermark: raw rows newer than the aggregates' watermarks (real-time part)."""
    h1 = homes["REFIT House 1"]
    sid = h1["series"]
    async with eng.connect() as c:
        wm = {v: await _watermark(c, f"reading_{v}") for v in ("1m", "1h", "1d")}
        raw_before = await c.scalar(text("SELECT count(*) FROM public.tb_reading"))
        start = max(wm.values()) + timedelta(seconds=30)  # newer than ALL three watermarks
        end = start + timedelta(minutes=90)
        await c.execute(
            text(
                "INSERT INTO public.tb_reading (ts, series_id, value, quality) "
                "SELECT g, :s, 1234, 0 FROM generate_series(CAST(:a AS timestamptz), "
                "CAST(:b AS timestamptz), interval '7 seconds') g"
            ),
            {"s": sid, "a": start, "b": end},
        )
        await c.commit()
    out: dict = {
        "watermarks": {k: v.isoformat() for k, v in wm.items()},
        "tail_rows_start": start.isoformat(),
        "tail_rows_end": end.isoformat(),
        "tail_rows": int((end - start).total_seconds() // 7) + 1,
    }
    try:
        now = end + timedelta(minutes=1)

        async def f_latest(i, s):
            return await latest_power(s, h1["home"], now=now)

        async def f_5m(i, s):
            return await meter_series(s, h1["home"], now - timedelta(days=1), now, 288, now=now)

        async def f_1h(i, s):
            return await meter_series(s, h1["home"], now - timedelta(days=45), now, 1080, now=now)

        async def f_1d(i, s):
            return await meter_series(s, h1["home"], now - timedelta(days=90), now, 90, now=now)

        async def f_week(i, s):
            return await meter_series(s, h1["home"], now - timedelta(days=7), now, 2000, now=now)

        for name, f in (
            ("latest_power", f_latest),
            ("series_week_15m_over_7d", f_week),
            ("series_5m_over_1d", f_5m),
            ("series_1h_over_45d", f_1h),
            ("series_1d_over_90d", f_1d),
        ):
            warm = await _measure(eng, f, varied=False)
            async with AsyncSession(eng, expire_on_commit=False) as s:
                cap.start()
                res = await f(0, s)
                stmts = cap.stop()
                plans = await explain(s, stmts)
            last = res if not isinstance(res, list) else (res[-1] if res else None)
            tail_visible = bool(
                last and getattr(last, "avg_w", getattr(last, "watts", 0)) == 1234.0
            )
            out[name] = {
                "warm": summarize_ms(warm),
                "plans": plans,
                "last_point_shows_tail": tail_visible,
                "target_p95_ms": 20.0 if name == "latest_power" else 100.0,
                "last_point": str(last)[:200],
            }
            log(f"tail {name}: {out[name]['warm']}")
        async with AsyncSession(eng) as s:
            lp = await latest_power(s, h1["home"], now=now)
        out["latest_power_sees_tail"] = bool(lp and lp.watts == 1234.0)
    finally:
        async with eng.connect() as c:
            await c.execute(
                text("DELETE FROM public.tb_reading WHERE series_id = :s AND ts >= :a"),
                {"s": sid, "a": start},
            )
            await c.commit()
            out["raw_rows_restored"] = (
                await c.scalar(text("SELECT count(*) FROM public.tb_reading")) == raw_before
            )
    results.record("latency", "lagging_watermark", out)


# ------------------------------------------------------------------ D: refresh cost
async def _timed_call(c, sql: str, **params) -> float:
    t0 = time.perf_counter()
    await c.execute(text(sql), params)
    return round(time.perf_counter() - t0, 3)


REFRESH = (
    "CALL refresh_continuous_aggregate(CAST(:v AS regclass), CAST(:a AS timestamptz), "
    "CAST(:b AS timestamptz){force})"
)
DAY = timedelta(days=1)


def _local_day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(hours=7)


async def _snap_diff(c) -> dict:
    row = (
        await c.execute(
            text(
                "SELECT count(*) AS rows_now, count(*) FILTER (WHERE o.series_id IS NULL) AS new_rows, "
                "count(*) FILTER (WHERE o.series_id IS NOT NULL AND (v.energy_wh IS DISTINCT FROM "
                "o.energy_wh OR v.n <> o.n OR v.covered_minutes <> o.covered_minutes)) AS rows_changed, "
                "coalesce(max(abs(v.energy_wh - o.energy_wh) / nullif(o.energy_wh, 0)), 0) AS max_rel_diff, "
                "(SELECT count(*) FROM public.audit_snap_1d s2 WHERE NOT EXISTS (SELECT 1 FROM "
                "public.reading_1d x WHERE x.series_id = s2.series_id AND x.bucket = s2.bucket)) "
                "AS rows_lost FROM public.reading_1d v LEFT JOIN public.audit_snap_1d o "
                "USING (series_id, bucket)"
            )
        )
    ).one()
    return {k: (float(v) if k == "max_rel_diff" else int(v)) for k, v in row._asdict().items()}


async def _checksum(c) -> str:
    return await c.scalar(
        text(
            "SELECT md5(string_agg(series_id || '|' || bucket || '|' || energy_wh || '|' || n || '|' "
            "|| covered_minutes, ',' ORDER BY series_id, bucket)) FROM public.reading_1d"
        )
    )


async def stage_refresh_cost(args) -> None:
    eng = make_engine(isolation_level="AUTOCOMMIT")
    out: dict = {}
    async with eng.connect() as c:
        await c.execute(text("SET work_mem = '256MB'"))
        sid = await c.scalar(
            text(
                "SELECT s.series_id FROM public.tb_series s JOIN public.tb_home h ON h.id = s.home_id "
                "WHERE h.name = 'REFIT House 1' AND s.kind = 'main'"
            )
        )
        before = await _checksum(c)
        await c.execute(text("DROP TABLE IF EXISTS public.audit_snap_1d"))
        await c.execute(
            text("CREATE TABLE public.audit_snap_1d AS SELECT * FROM public.reading_1d")
        )
        d0 = _local_day_start(date(2026, 6, 15))
        marker = d0 + timedelta(hours=10, seconds=0.5)
        marker2 = _local_day_start(date(2026, 10, 28)) + timedelta(hours=9, seconds=0.5)
        day2 = _local_day_start(date(2026, 10, 28))
        try:
            # 1. one invalidated day: insert one reading, refresh 1m, 1h, 1d on that day only
            await c.execute(
                text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, 777)"),
                {"t": marker, "s": sid},
            )
            single = {}
            for res in ("1m", "1h", "1d"):
                single[res] = await _timed_call(
                    c, REFRESH.format(force=""), v=f"public.reading_{res}", a=d0, b=d0 + DAY
                )
            out["one_invalidated_day_refresh_seconds"] = single
            # 2. policy-sized windows with one invalidation (policy offsets of public.set_policies(true))
            now = datetime.now(UTC)
            await c.execute(
                text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, 777)"),
                {"t": marker2, "s": sid},
            )
            policy = {}
            for res, off, end_off, step in (
                ("1m", 7, timedelta(minutes=1), timedelta(minutes=1)),
                ("1h", 30, timedelta(hours=1), timedelta(hours=1)),
                ("1d", 60, timedelta(hours=1), DAY),
            ):
                a = _snap_floor(now - timedelta(days=off), step)
                b = _snap_floor(now - end_off, step)
                policy[res] = await _timed_call(
                    c, REFRESH.format(force=""), v=f"public.reading_{res}", a=a, b=b
                )
            out["policy_window_with_one_invalidation_seconds"] = policy
            no_inval = {}
            for res, off, end_off, step in (
                ("1m", 7, timedelta(minutes=1), timedelta(minutes=1)),
                ("1h", 30, timedelta(hours=1), timedelta(hours=1)),
                ("1d", 60, timedelta(hours=1), DAY),
            ):
                a = _snap_floor(now - timedelta(days=off), step)
                b = _snap_floor(now - end_off, step)
                no_inval[res] = await _timed_call(
                    c, REFRESH.format(force=""), v=f"public.reading_{res}", a=a, b=b
                )
            out["policy_window_nothing_to_do_seconds"] = no_inval
            w0 = _local_day_start(date(2026, 5, 1))
            # 4. what dominates 1d: the query it runs over reading_1h, view vs materialization table
            mat = await c.scalar(
                text(
                    "SELECT format('%I.%I', materialization_hypertable_schema, materialization_hypertable_name)"
                    " FROM timescaledb_information.continuous_aggregates WHERE view_name = 'reading_1h'"
                )
            )
            q = (
                "SELECT time_bucket('1 day', bucket, 'Asia/Ho_Chi_Minh') b, series_id, "
                "sum(avg_w * n) / sum(n), min(min_w), max(max_w), sum(n), sum(energy_wh), "
                "sum(covered_minutes) FROM {src} WHERE bucket >= '{a}' AND bucket < '{b}' "
                "GROUP BY 1, 2"
            )
            plans = {}
            for label, src in (
                ("over_realtime_view_reading_1h", "public.reading_1h"),
                ("over_materialization_table", mat),
            ):
                qq = q.format(src=src, a=w0, b=w0 + timedelta(days=30)).replace(
                    "sum(covered_minutes)",
                    "sum(covered_minutes)" if "reading_1h" in src else "sum(covered_minutes)",
                )
                raw = await (await c.get_raw_connection()).driver_connection.fetch(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + qq
                )
                plan = json.loads(raw[0][0]) if isinstance(raw[0][0], str) else raw[0][0]
                plans[label] = trim_plan(plan)
            out["query_plan_30d_window"] = plans
            # 5. restore
            for ts in (marker, marker2):
                await c.execute(
                    text("DELETE FROM public.tb_reading WHERE series_id = :s AND ts = :t"),
                    {"s": sid, "t": ts},
                )
            for res in ("1m", "1h", "1d"):
                await _timed_call(
                    c, REFRESH.format(force=""), v=f"public.reading_{res}", a=d0, b=d0 + DAY
                )
                await _timed_call(
                    c,
                    REFRESH.format(force=""),
                    v=f"public.reading_{res}",
                    a=_local_day_start(date(2026, 10, 28)),
                    b=_local_day_start(date(2026, 10, 29)),
                )
            out["reading_1d_checksum_restored_after_marker_cycle"] = (await _checksum(c)) == before
            out["reading_1d_diff_vs_snapshot_after_marker_cycle"] = await _snap_diff(c)
            # 3b. forced recompute of a 30-day window (what the backfill windows cost)
            w0 = _local_day_start(date(2026, 5, 1))
            forced = {}
            for res in ("1m", "1h", "1d"):
                forced[res] = await _timed_call(
                    c,
                    REFRESH.format(force=", force => true"),
                    v=f"public.reading_{res}",
                    a=w0,
                    b=w0 + timedelta(days=30),
                )
            out["forced_30_day_window_seconds"] = forced
            out["reading_1d_diff_vs_snapshot_after_forced_recompute"] = await _snap_diff(c)
            out["reading_1d_checksum_after_forced_recompute_equals_before"] = (
                await _checksum(c)
            ) == before
        finally:
            # always restore the audit data, also after an error: drop the markers, re-refresh
            # their days, recompress the touched chunks, drop the snapshot table
            for ts in (marker, marker2):
                await c.execute(
                    text("DELETE FROM public.tb_reading WHERE series_id = :s AND ts = :t"),
                    {"s": sid, "t": ts},
                )
            for res in ("1m", "1h", "1d"):
                await _timed_call(
                    c, REFRESH.format(force=""), v=f"public.reading_{res}", a=d0, b=d0 + DAY
                )
                await _timed_call(
                    c, REFRESH.format(force=""), v=f"public.reading_{res}", a=day2, b=day2 + DAY
                )
            for t in (marker, marker2):
                chunks = await c.execute(
                    text(
                        "SELECT show_chunks('public.tb_reading', newer_than => CAST(:a AS timestamptz), "
                        "older_than => CAST(:b AS timestamptz))"
                    ),
                    {"a": t - timedelta(hours=1), "b": t + timedelta(hours=1)},
                )
                for (ch,) in chunks.all():
                    await c.execute(
                        text(
                            "SELECT compress_chunk(CAST(:c AS regclass), if_not_compressed => true)"
                        ),
                        {"c": ch},
                    )
            await c.execute(text("DROP TABLE IF EXISTS public.audit_snap_1d"))
            out["markers_left_after_cleanup"] = await c.scalar(
                text(
                    "SELECT count(*) FROM public.tb_reading WHERE series_id = :s AND ts IN (:a, :b)"
                ),
                {"s": sid, "a": marker, "b": marker2},
            )
    await eng.dispose()
    for k, v in out.items():
        results.record("refresh_cost", k, v)
    log(f"refresh cost: {json.dumps(out)[:900]}")


def _snap_floor(ts: datetime, step: timedelta) -> datetime:
    origin = datetime(2000, 1, 1, 17, tzinfo=UTC)
    return origin + ((ts - origin) // step) * step
