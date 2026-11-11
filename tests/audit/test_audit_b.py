"""Audit part B: failure drills (scratch DB), copilot isolation (audit DB), rebuild from empty.

Run with `pytest -m audit tests/audit/test_audit_b.py` against the isolated audit server.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.energy.services.aggregates import backfill_aggregates
from app.modules.energy.services.meter import meter_series
from app.modules.ops.services.ingest import ReadingRow, ingest_readings
from tests.audit import results
from tests.audit.part_b2 import PAUSED_POLICIES
from tests.audit.support import create_scratch, drop_scratch
from tests.db.conftest import run_alembic
from tests.db.test_roles import (
    COPILOT,
    COPILOT_VIEWS,
    as_role,
    denied,
    reset,
    set_token,
    table_denied,
    view_count,
    view_ids,
)

pytestmark = pytest.mark.audit
SERIAL = "REFIT-H1"
WATTS = 600.0


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def rows(start: datetime, minutes: int, value: float = WATTS, quality: int = 0, step_s: int = 10):
    return [
        ReadingRow(start + timedelta(seconds=s), "Aggregate", value, quality)
        for s in range(0, minutes * 60, step_s)
    ]


# ------------------------------------------------------------------ B: failure drills
async def _provision(s: AsyncSession) -> int:
    """Owner, home, meter SERIAL and its Aggregate main series; returns the home id."""
    user = await s.scalar(
        text("INSERT INTO public.tb_users (email) VALUES ('drill@example.invalid') RETURNING id")
    )
    home = await s.scalar(
        text("INSERT INTO public.tb_home (name, home_type) VALUES ('Drill', 'house') RETURNING id")
    )
    await s.execute(
        text("INSERT INTO public.tb_home_member (home_id, user_id, role) VALUES (:h, :u, 'owner')"),
        {"h": home, "u": user},
    )
    meter = await s.scalar(
        text(
            "INSERT INTO public.tb_meter (serial, home_id, status) VALUES (:s, :h, 'active') "
            "RETURNING id"
        ),
        {"s": SERIAL, "h": home},
    )
    await s.execute(
        text(
            "INSERT INTO public.tb_series (home_id, kind, meter_id, source_channel, metric, unit) "
            "VALUES (:h, 'main', :m, 'Aggregate', 'power_w', 'W')"
        ),
        {"h": home, "m": meter},
    )
    return home


@pytest.fixture(scope="module")
async def drill():
    dsn = await create_scratch("wattprint_audit_b")
    eng = create_async_engine(dsn)
    async with AsyncSession(eng, expire_on_commit=False) as s:
        home = await _provision(s)
        await s.commit()
    ac = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    try:
        yield {"eng": eng, "ac": ac, "home": home}
    finally:
        await eng.dispose()
        await ac.dispose()
        await drop_scratch("wattprint_audit_b")


async def _ingest(eng, batch):
    async with AsyncSession(eng, expire_on_commit=False) as s:
        res = await ingest_readings(s, SERIAL, batch, "drill")
        await s.commit()
        return res


async def _refresh(ac, a, b):
    async with ac.connect() as c:
        assert await backfill_aggregates(c, a, b) == []


async def _hour(eng, hour: datetime):
    async with eng.connect() as c:
        return (
            await c.execute(
                text(
                    "SELECT n, energy_wh, covered_minutes FROM public.reading_1h WHERE bucket = :b "
                    "AND series_id = (SELECT series_id FROM public.tb_series WHERE kind='main')"
                ),
                {"b": hour},
            )
        ).first()


async def test_drill_duplicate_batch(drill):
    eng, ac = drill["eng"], drill["ac"]
    batch = rows(at(10, 2), 60)
    first = await _ingest(eng, batch)
    second = await _ingest(eng, batch)
    await _refresh(ac, at(10, 0), at(10, 12))
    h = await _hour(eng, at(10, 2))
    out = {
        "first_new": first.rows_new,
        "second_new": second.rows_new,
        "second_dup": second.rows_dup,
        "hour_n": h.n,
        "hour_wh": h.energy_wh,
        "covered_minutes": h.covered_minutes,
    }
    results.record("drills", "duplicate_batch", out)
    assert (first.rows_new, second.rows_new, second.rows_dup) == (360, 0, 360)
    assert (h.n, h.covered_minutes) == (360, 60)
    assert h.energy_wh == pytest.approx(WATTS)  # 600 W for one hour


async def test_drill_out_of_order_and_late_batch(drill):
    eng, ac = drill["eng"], drill["ac"]
    later = rows(at(11, 5), 60)
    earlier = list(reversed(rows(at(11, 3), 60)))  # shuffled order, older than the first batch
    await _ingest(eng, later)
    await _refresh(ac, at(11, 0), at(11, 12))  # materialized with the later hour only
    res = await _ingest(eng, earlier)  # late data inside the materialized range
    await _refresh(ac, at(11, 0), at(11, 12))  # backfill picks it up
    h3, h5 = await _hour(eng, at(11, 3)), await _hour(eng, at(11, 5))
    async with eng.connect() as c:
        last_ts = await c.scalar(text("SELECT last_ts FROM public.tb_ingest_checkpoint LIMIT 1"))
    results.record(
        "drills",
        "out_of_order",
        {
            "late_rows_new": res.rows_new,
            "late_hour_wh": h3.energy_wh,
            "first_hour_wh": h5.energy_wh,
            "checkpoint_not_moved_back": last_ts >= at(11, 5),
        },
    )
    assert res.rows_new == 360
    assert h3.energy_wh == pytest.approx(WATTS) and h5.energy_wh == pytest.approx(WATTS)
    assert h3.n == 360 and last_ts >= at(11, 5)


async def test_drill_gap_longer_than_an_hour(drill):
    eng, ac = drill["eng"], drill["ac"]
    await _ingest(eng, rows(at(12, 3), 30) + rows(at(12, 5), 30))  # 90 minute hole
    await _refresh(ac, at(12, 0), at(12, 12))
    h4 = await _hour(eng, at(12, 4))
    async with AsyncSession(eng) as s:
        pts = await meter_series(s, drill["home"], at(12, 2), at(12, 7), 5, now=at(12, 8))
    async with eng.connect() as c:
        day = (
            await c.execute(
                text(
                    "SELECT energy_wh, covered_minutes FROM public.reading_1d WHERE bucket = :b "
                    "AND series_id = (SELECT series_id FROM public.tb_series WHERE kind='main')"
                ),
                {"b": datetime(2026, 3, 11, 17, tzinfo=UTC)},
            )
        ).first()
    stamps = [p.ts for p in pts]
    results.record(
        "drills",
        "gap_over_1h",
        {
            "hour_in_gap_has_row": h4 is not None,
            "points": [p.ts.isoformat() for p in pts],
            "day_energy_wh": day.energy_wh,
            "day_covered_minutes": day.covered_minutes,
        },
    )
    assert h4 is None  # a gap is a gap: no row, nothing filled in
    assert stamps == [at(12, 3), at(12, 5)]
    assert [p.energy_wh for p in pts] == pytest.approx([300.0, 300.0])
    assert day.covered_minutes == 60 and day.energy_wh == pytest.approx(600.0)


async def test_drill_issues_flagged_rows(drill):
    eng, ac = drill["eng"], drill["ac"]
    await _ingest(eng, rows(at(13, 3), 30) + rows(at(13, 3, 30), 30, value=9999.0, quality=1))
    await _refresh(ac, at(13, 0), at(13, 12))
    h = await _hour(eng, at(13, 3))
    async with eng.connect() as c:
        raw = (
            await c.execute(
                text(
                    "SELECT count(*) AS n, count(*) FILTER (WHERE quality & 1 = 1) AS flagged, "
                    "max(value) FILTER (WHERE quality & 1 = 1) AS flagged_value "
                    "FROM public.tb_reading WHERE ts >= :a AND ts < :b"
                ),
                {"a": at(13, 3), "b": at(13, 4)},
            )
        ).one()
    results.record(
        "drills",
        "issues_flagged",
        {
            "raw_rows": raw.n,
            "raw_flagged": raw.flagged,
            "view_n": h.n,
            "view_wh": h.energy_wh,
            "covered_minutes": h.covered_minutes,
        },
    )
    assert (raw.n, raw.flagged) == (360, 180)  # kept in raw for audit
    assert h.n == 180 and h.covered_minutes == 30  # excluded from the aggregates
    assert h.energy_wh == pytest.approx(300.0)


async def test_drill_stopped_refresh_job_reads_stay_correct(drill):
    eng, ac, home = drill["eng"], drill["ac"], drill["home"]
    async with ac.connect() as c:
        await c.execute(text(PAUSED_POLICIES))  # created and paused in one transaction
        jobs = (
            await c.execute(
                text(
                    "SELECT proc_name, scheduled FROM timescaledb_information.jobs "
                    "WHERE hypertable_name IS NOT NULL"
                )
            )
        ).all()
    refresh_jobs = [j for j in jobs if j.proc_name == "policy_refresh_continuous_aggregate"]
    assert len(refresh_jobs) == 6 and not any(j.scheduled for j in jobs)
    await _ingest(eng, rows(at(15, 3), 60))  # newer than every watermark, no refresh will run
    async with eng.connect() as c:
        mat = await c.scalar(
            text(
                "SELECT count(*) FROM _timescaledb_internal.%s" % (await _mat_name(c, "reading_1h"))
                + " WHERE bucket = :b"
            ),
            {"b": at(15, 3)},
        )
    async with AsyncSession(eng) as s:
        m5 = await meter_series(s, home, at(15, 3), at(15, 4), 12, now=at(15, 6))  # 5 minute step
        h1 = await meter_series(s, home, at(15, 3), at(15, 4), 1, now=at(15, 6))  # 1 hour step
        d1 = await meter_series(s, home, at(15, 0), at(16, 0), 1, now=at(15, 6))  # 1 day step
    results.record(
        "drills",
        "stopped_refresh_job",
        {
            "refresh_jobs_paused": len(refresh_jobs),
            "materialized_rows_for_new_hour": mat,
            "points_5m": len(m5),
            "hour_wh": h1[0].energy_wh,
            "day_wh": d1[0].energy_wh,
        },
    )
    assert mat == 0  # trivial by construction (nothing refreshed); the reads below are the test
    assert len(m5) == 12 and sum(p.energy_wh for p in m5) == pytest.approx(WATTS)
    assert h1[0].energy_wh == pytest.approx(WATTS)
    assert d1[0].energy_wh == pytest.approx(WATTS)
    # late rows inside an already materialized range (the 03-12 hole 04:00-05:00 was
    # materialized as empty) while the refresh jobs are stopped: reads are STALE until a refresh
    late = await _ingest(eng, rows(at(12, 4), 30))
    async with AsyncSession(eng) as s:
        stale = await meter_series(s, home, at(12, 4), at(12, 5), 1, now=at(15, 6))
    async with eng.connect() as c:
        raw_late = await c.scalar(
            text("SELECT count(*) FROM public.tb_reading WHERE ts >= :a AND ts < :b"),
            {"a": at(12, 4), "b": at(12, 5)},
        )
    await _refresh(ac, at(12, 0), at(12, 12))  # what the stopped job would have done
    async with AsyncSession(eng) as s:
        fresh = await meter_series(s, home, at(12, 4), at(12, 5), 1, now=at(15, 6))
    results.record(
        "drills",
        "stopped_refresh_job_late_data",
        {
            "late_rows_new": late.rows_new,
            "raw_rows_in_hole_hour": raw_late,
            "points_while_job_stopped": len(stale),
            "points_after_manual_refresh": len(fresh),
            "energy_after_refresh_wh": fresh[0].energy_wh if fresh else None,
            "note": "late rows inside a materialized range are NOT visible until a refresh runs",
        },
    )
    assert late.rows_new == 180 and raw_late == 180
    assert stale == []  # stale read: the data is in raw but not in the aggregates
    assert [p.energy_wh for p in fresh] == pytest.approx([300.0])
    async with ac.connect() as c:
        await c.execute(text("SELECT public.set_policies(false)"))


async def _mat_name(c, view: str) -> str:
    return await c.scalar(
        text(
            "SELECT materialization_hypertable_name "
            "FROM timescaledb_information.continuous_aggregates "
            "WHERE view_name = :v"
        ),
        {"v": view},
    )


# ------------------------------------------------------------------ C: copilot isolation
async def _two_homes(c):
    rows_ = (
        await c.execute(
            text(
                "SELECT h.id, h.name FROM public.tb_home h "
                "WHERE h.name IN ('REFIT House 1', 'REFIT House 2') "
                "ORDER BY h.name"
            )
        )
    ).all()
    out = []
    for r in rows_:
        token = await c.scalar(
            text("INSERT INTO public.tb_scope_token (home_id) VALUES (:h) RETURNING token"),
            {"h": r.id},
        )
        sids = set(
            (
                await c.execute(
                    text("SELECT series_id FROM public.tb_series WHERE home_id = :h"), {"h": r.id}
                )
            ).scalars()
        )
        out.append({"home": r.id, "token": token, "series": sids})
    return out


async def test_copilot_isolation_on_loaded_data(engine):
    async with engine.connect() as c:
        a, b = await _two_homes(c)
        own_1d = await c.scalar(
            text("SELECT count(*) FROM public.reading_1d WHERE series_id = ANY(:s)"),
            {"s": list(a["series"])},
        )
        checked = {}
        for home, other in ((a, b), (b, a)):
            await as_role(c, COPILOT, home["token"])
            assert await view_ids(c, "home") == {home["home"]}
            assert await view_ids(c, "series", "series_id") == home["series"]
            for fam in ("reading", "device_estimate"):
                for res in ("1m", "1h", "1d"):
                    got = await c.scalar(
                        text(f"SELECT count(DISTINCT series_id) FROM copilot_ro.{fam}_{res}")
                    )
                    ids = await view_ids(c, f"{fam}_{res}", "series_id")
                    assert ids <= home["series"] and ids.isdisjoint(other["series"])
                    checked[f"{fam}_{res}_series_visible"] = got
            await reset(c)
        # row counts through the view equal the real count of the own series (no leakage, no loss)
        await as_role(c, COPILOT, a["token"])
        assert await view_count(c, "reading_1d") == own_1d
        # token handling
        for bad in ("", "not-a-uuid", str(uuid.uuid4()), "'; DROP TABLE public.tb_home; --"):
            await set_token(c, bad)
            for view in COPILOT_VIEWS:
                assert await view_count(c, view) == 0, (view, bad)
        await set_token(c, a["token"])
        assert await view_ids(c, "home") == {a["home"]}
        # no direct table access, no writes
        await denied(c, "SELECT count(*) FROM public.tb_reading")
        await denied(c, "SELECT count(*) FROM public.reading_1d")
        await denied(c, "INSERT INTO public.tb_reading (ts, series_id, value) VALUES (now(), 1, 1)")
        await denied(c, "UPDATE public.tb_home SET name = 'x'")
        await denied(c, "DELETE FROM public.tb_home")
        await denied(c, "SELECT token FROM public.tb_scope_token")
        await reset(c)
        for table in (
            "public.tb_reading",
            "public.tb_device_estimate",
            "public.tb_home",
            "public.tb_bill",
        ):
            assert await table_denied(c, COPILOT, table)
        await c.rollback()  # tokens were inserted in this transaction
    results.record(
        "isolation",
        "audit_db",
        {
            "homes_checked": 2,
            "own_reading_1d_rows_visible": own_1d,
            "views_checked": len(COPILOT_VIEWS),
            "bad_tokens_checked": 4,
            **checked,
        },
    )


# ------------------------------------------------------------------ G: rebuild from empty
def test_rebuild_from_empty():
    name = "wattprint_audit_g"
    import asyncio

    async def go():
        dsn = await create_scratch(name, migrate=False)
        try:
            run_alembic(dsn, "upgrade", "head")  # the only schema step
            eng = create_async_engine(dsn)
            async with eng.connect() as c:
                n = await c.scalar(text("SELECT count(*) FROM public.tb_reading"))
                series = await c.scalar(text("SELECT count(*) FROM public.tb_series"))
                tiers = await c.scalar(text("SELECT count(*) FROM public.tb_tariff_tier"))
                types = await c.scalar(text("SELECT count(*) FROM public.cat_device_type"))
                jobs = await c.scalar(
                    text(
                        "SELECT count(*) FROM timescaledb_information.jobs "
                        "WHERE hypertable_name IS NOT NULL"
                    )
                )
            await eng.dispose()
            out = {
                "readings": n,
                "series": series,
                "tariff_tiers_seeded": tiers,
                "device_types_seeded": types,
                "policy_jobs_after_migration": jobs,
                "manual_steps": 0,
            }
            results.record("rebuild", "from_empty", out)
            assert n == 0 and series == 0 and tiers > 0 and types > 0  # seed revision skipped
        finally:
            await drop_scratch(name)

    asyncio.run(go())
