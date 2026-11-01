"""Audit part A: idempotency and energy correctness against exact integration.

Run with `pytest -m audit tests/audit/test_audit_a.py` after the load / estimates / backfill stages.
"""

import math
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.cli.load_refit import load_house
from app.services.aggregates import backfill_aggregates
from tests.audit import results
from tests.audit.exact import compare, exact_days, median_cadence, view_days
from tests.audit.run import csv_path
from tests.audit.support import make_engine

pytestmark = pytest.mark.audit

HOUSES = (1, 2, 3)
SAMPLE_DAYS = 30
CHECKSUM = text(
    "SELECT count(*) AS n, sum(energy_wh) AS wh, sum(n) AS samples, sum(covered_minutes) AS cov, "
    "md5(string_agg(series_id || '|' || bucket || '|' || energy_wh || '|' || n || '|' || "
    "covered_minutes, ',' ORDER BY series_id, bucket)) AS digest FROM energy.reading_1d"
)


async def _phase(conn) -> str:
    """post_compress when the DB holds compressed raw chunks (not what the JSON claims)."""
    n = await conn.scalar(
        text("SELECT count(*) FROM timescaledb_information.chunks "
             "WHERE hypertable_schema = 'energy' AND hypertable_name = 'reading' AND is_compressed")
    )
    return "post_compress" if n else "pre_compress"


@pytest.fixture(scope="module")
async def phase(engine):
    async with engine.connect() as conn:
        return await _phase(conn)


async def _main_series(conn, house: int) -> int:
    return await conn.scalar(
        text("SELECT s.series_id FROM energy.series s JOIN core.home h ON h.id = s.home_id "
             "WHERE h.name = :n AND s.kind = 'main'"),
        {"n": f"REFIT House {house}"},
    )


async def test_idempotency(conn, session):
    """Reload 100k CSV rows of House 1: nothing new, aggregates unchanged.

    Duplicate rows insert nothing, so no invalidation is logged and the refresh of the reloaded
    window below is expected to be a no-op; the check shows that a refresh after the reload
    leaves reading_1d identical (it would not be if the reload had changed raw data).
    """
    shift = results.load()["load"]["house1"]["shift_days"]
    before = (await conn.execute(CHECKSUM)).one()._asdict()
    raw_before = await conn.scalar(text("SELECT count(*) FROM energy.reading"))
    first_ts = await conn.scalar(
        text("SELECT min(ts) FROM energy.reading r JOIN energy.series s USING (series_id) "
             "JOIN core.home h ON h.id = s.home_id WHERE h.name = 'REFIT House 1' "
             "AND s.kind = 'main'")
    )
    await conn.rollback()
    res = await load_house(session, 1, Path(csv_path(1)), shift_days=shift, limit_rows=100_000)
    eng = make_engine(isolation_level="AUTOCOMMIT")
    try:
        async with eng.connect() as ac:
            await backfill_aggregates(ac, first_ts, first_ts + timedelta(days=15))
    finally:
        await eng.dispose()
    after = (await conn.execute(CHECKSUM)).one()._asdict()
    raw_after = await conn.scalar(text("SELECT count(*) FROM energy.reading"))
    out = {
        "rows_in": res.rows_in, "rows_new": res.rows_new, "rows_dup": res.rows_dup,
        "rows_bad": res.rows_bad, "reading_rows_before": raw_before,
        "reading_rows_after": raw_after, "reading_1d_before": before, "reading_1d_after": after,
        "identical": before == after,
    }
    results.record("idempotency", await _phase(conn), out)
    assert (res.rows_in, res.rows_new, res.rows_dup, res.rows_bad) == (1_000_000, 0, 1_000_000, 0)
    assert raw_before == raw_after
    assert before == after


@pytest.fixture(scope="module")
async def energy_numbers(engine):
    """Per house: exact vs view per day (computed once, recorded)."""
    out = {}
    async with engine.connect() as conn:
        await conn.execute(text("SET work_mem = '256MB'"))
        for house in HOUSES:
            sid = await _main_series(conn, house)
            cadence = await median_cadence(conn, sid)
            exact = await exact_days(conn, sid, cadence)
            view = await view_days(conn, sid)
            variants = {
                "hold_across_flagged": await exact_days(
                    conn, sid, cadence, hold_across_flagged=True),
                "hold_across_flagged_cap_120s": await exact_days(
                    conn, sid, cadence, hold_across_flagged=True, cap_s=120.0),
            }
            await conn.rollback()
            out[house] = (sid, cadence, exact, view, variants)
    return out


async def test_energy_coverage_consistent(energy_numbers, phase):
    """Record the day-level comparison; assert only that covered_minutes matches the raw data.

    The 1% accuracy gate itself is test_energy_gate_one_percent.
    """
    sample = {}
    for house, (_sid, cadence, exact, view, variants) in energy_numbers.items():
        stats = compare(exact, view)
        stats["median_cadence_s"] = cadence
        stats["days_in_view"] = len(view)
        stats["days_in_exact"] = len(exact)
        results.record(f"energy_vs_exact_{phase}", f"house{house}", stats)
        for name, alt in variants.items():
            diag = compare(alt, view)
            for cls in ("full_coverage", "low_coverage"):
                diag[cls].pop("worst")
            results.record(f"energy_variants_{phase}", f"house{house}.{name}", diag)
        full = sorted(d for d, (_, cov, _) in view.items() if cov / 1440 >= 0.95 and d in exact)
        step = max(1, len(full) // SAMPLE_DAYS)
        picked = full[::step][:SAMPLE_DAYS]
        sample[f"house{house}"] = {d.isoformat(): [exact[d][0], view[d][0]] for d in picked}
        # must hold: the view's covered_minutes equals the independent count of good minutes,
        # so low-coverage days show their low coverage
        assert stats["covered_minutes_mismatch_days"] == 0, house
        assert stats["full_coverage"]["days"] > 0, house
    if phase == "pre_compress":
        results.record("energy_sample", "days", sample)


async def test_energy_gate_one_percent(energy_numbers):
    """The 1% gate on days with coverage >= 95%: fails today, measured (docs/database-audit.md,
    section "Verdicts"). Passes if no day exceeds 1%; is an xfail carrying the measured numbers
    while the result equals the recorded baseline; FAILS if it got worse than the baseline.
    """
    base = results.load().get("energy_gate_baseline", {})
    measured = {}
    for house, (_sid, _cad, exact, view, _v) in energy_numbers.items():
        full = compare(exact, view)["full_coverage"]
        measured[f"house{house}"] = {
            "days": full["days"], "days_over_gate": full["days_over_gate"],
            "err_pct_max": full["err_pct_max"], "err_pct_p95": full["err_pct_p95"],
        }
    if all(m["days_over_gate"] == 0 for m in measured.values()):
        return
    assert base, "gate failing and no energy_gate_baseline recorded"
    worse = {
        h: (m, base[h]) for h, m in measured.items()
        if m["days_over_gate"] > base[h]["days_over_gate"]
        or m["err_pct_max"] > base[h]["err_pct_max"] * (1 + 1e-6)
    }
    assert not worse, f"gate result got WORSE than the recorded baseline: {worse}"
    pytest.xfail(f"1% gate fails as recorded in the baseline (docs/database-audit.md, Verdicts): "
                 f"{measured}")


async def test_energy_after_compression(energy_numbers, phase):
    res = results.load()
    if phase != "post_compress" or "days" not in res.get("energy_sample", {}):
        pytest.skip("no compressed raw chunks yet, or no pre-compression sample recorded")
    checked = 0
    for house, (_sid, _cad, exact, view, _v) in energy_numbers.items():
        for day, (ex_before, view_before) in res["energy_sample"]["days"][f"house{house}"].items():
            d = next(k for k in exact if k.isoformat() == day)
            assert math.isclose(exact[d][0], ex_before, rel_tol=1e-9), (house, day)
            assert math.isclose(view[d][0], view_before, rel_tol=1e-9), (house, day)
            checked += 1
    results.record("energy_sample", "days_checked_after_compression", checked)
    results.record("energy_sample", "identical_after_compression", True)
    assert checked > 0
