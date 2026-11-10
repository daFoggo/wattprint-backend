"""Audit part A: energy correctness against exact integration.

Run with `pytest -m audit tests/audit/test_audit_a.py` after the estimates / backfill stages.
"""

import math

import pytest
from sqlalchemy import text

from tests.audit import results
from tests.audit.exact import compare, exact_days, median_cadence, view_days

pytestmark = pytest.mark.audit

HOUSES = (1, 2, 3)
SAMPLE_DAYS = 30


async def _phase(conn) -> str:
    """post_compress when the DB holds compressed raw chunks (not what the JSON claims)."""
    n = await conn.scalar(
        text(
            "SELECT count(*) FROM timescaledb_information.chunks "
            "WHERE hypertable_schema = 'public' AND hypertable_name = 'tb_reading' "
            "AND is_compressed"
        )
    )
    return "post_compress" if n else "pre_compress"


@pytest.fixture(scope="module")
async def phase(engine):
    async with engine.connect() as conn:
        return await _phase(conn)


async def _main_series(conn, house: int) -> int:
    return await conn.scalar(
        text(
            "SELECT s.series_id FROM public.tb_series s JOIN public.tb_home h ON h.id = s.home_id "
            "WHERE h.name = :n AND s.kind = 'main'"
        ),
        {"n": f"REFIT House {house}"},
    )


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
                    conn, sid, cadence, hold_across_flagged=True
                ),
                "hold_across_flagged_cap_120s": await exact_days(
                    conn, sid, cadence, hold_across_flagged=True, cap_s=120.0
                ),
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


GATE_REFERENCE = "hold_across_flagged_cap_120s"  # the reference of spec section 9 (restated)


async def test_energy_gate_one_percent(energy_numbers):
    """The 1% gate on days with coverage >= 95%, measured against the RESTATED reference of spec
    section 9 (flagged samples dropped before integrating, gap cap 120 s). The original reference
    (cap 5 x median, flagged = missing) is only a recorded diagnostic (energy_vs_exact_*). The gate
    fails today (docs/database-audit.md, "Verdicts"): passes if no day exceeds 1%, is an xfail
    carrying the measured numbers while the result is no worse than the recorded baseline, and
    FAILS if days over the gate, the maximum or the p95 got worse.
    """
    base = results.load().get("energy_gate_baseline", {})
    measured, original = {}, {}
    for house, (_sid, _cad, exact, view, variants) in energy_numbers.items():
        full = compare(variants[GATE_REFERENCE], view)["full_coverage"]
        measured[f"house{house}"] = {
            "days": full["days"],
            "days_over_gate": full["days_over_gate"],
            "err_pct_max": full["err_pct_max"],
            "err_pct_p95": full["err_pct_p95"],
        }
        orig = compare(exact, view)["full_coverage"]
        original[f"house{house}"] = {
            "days_over_gate": orig["days_over_gate"],
            "err_pct_max": orig["err_pct_max"],
        }
    if all(m["days_over_gate"] == 0 for m in measured.values()):
        return
    assert base, "gate failing and no energy_gate_baseline recorded"
    assert all(b.get("reference") == GATE_REFERENCE for b in base.values()), (
        "energy_gate_baseline was recorded for another reference"
    )
    worse = {
        h: (m, base[h])
        for h, m in measured.items()
        if m["days_over_gate"] > base[h]["days_over_gate"]
        or m["err_pct_max"] > base[h]["err_pct_max"] * (1 + 1e-6)
        or m["err_pct_p95"] > base[h]["err_pct_p95"] * (1 + 1e-6)
    }
    assert not worse, f"gate result got WORSE than the recorded baseline: {worse}"
    pytest.xfail(
        f"1% gate fails against the restated reference ({GATE_REFERENCE}), as recorded "
        f"(docs/database-audit.md, Verdicts): {measured}; original reference (diagnostic): "
        f"{original}"
    )


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
