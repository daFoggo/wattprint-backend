"""Reference calculation for the energy audit (reads raw tables; product code must not).

Exact value per local day (Asia/Ho_Chi_Minh): zero-order-hold integration of the raw samples,
dt_i = least(lead(ts) - ts, 5 x median cadence), only samples with quality & 1 = 0 contribute.
"""

from datetime import datetime

from sqlalchemy import text

CADENCE_FACTOR = 5

_MEDIAN = text(
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY dt) FROM ("
    " SELECT extract(epoch FROM ts - lag(ts) OVER (ORDER BY ts)) AS dt"
    " FROM energy.reading WHERE series_id = :sid) x WHERE dt IS NOT NULL"
)

def _exact_sql(drop_flagged: bool) -> str:
    # Primary reference: the window runs over ALL raw samples and flagged ones are filtered out
    # afterwards, so flagged time counts as missing. Variant: flagged samples are dropped BEFORE
    # the window, so the previous good sample holds across them (like a minute average does).
    inner_where = "series_id = :sid" + (" AND quality & 1 = 0" if drop_flagged else "")
    return (
        "SELECT time_bucket('1 day', ts, 'Asia/Ho_Chi_Minh') AS day,"
        "       sum(value::double precision * dt) / 3600.0 AS exact_wh,"
        "       count(DISTINCT date_trunc('minute', ts)) AS good_minutes"
        " FROM ("
        "  SELECT ts, value, quality,"
        "         least(extract(epoch FROM lead(ts) OVER (ORDER BY ts) - ts), :cap) AS dt"
        f"  FROM energy.reading WHERE {inner_where}) q"
        " WHERE quality & 1 = 0 AND dt IS NOT NULL"
        " GROUP BY 1 ORDER BY 1"
    )


_EXACT = text(_exact_sql(False))
_EXACT_HOLD_FLAGGED = text(_exact_sql(True))

_VIEW = text(
    "SELECT bucket AS day, energy_wh, covered_minutes, n FROM energy.reading_1d"
    " WHERE series_id = :sid ORDER BY bucket"
)


async def median_cadence(conn, series_id: int) -> float:
    return float(await conn.scalar(_MEDIAN, {"sid": series_id}))


async def exact_days(
    conn, series_id: int, cadence_s: float, *, hold_across_flagged: bool = False,
    cap_s: float | None = None,
) -> dict[datetime, tuple[float, int]]:
    """day -> (exact_wh, minutes holding at least one good sample).

    Defaults are the audit reference (cap 5 x median cadence, flagged time missing). The keyword
    options only serve diagnostic variants.
    """
    stmt = _EXACT_HOLD_FLAGGED if hold_across_flagged else _EXACT
    cap = cap_s if cap_s is not None else CADENCE_FACTOR * cadence_s
    rows = await conn.execute(stmt, {"sid": series_id, "cap": cap})
    return {r.day: (float(r.exact_wh), int(r.good_minutes)) for r in rows}


async def view_days(conn, series_id: int) -> dict[datetime, tuple[float, int, int]]:
    """day -> (energy_wh, covered_minutes, n) from energy.reading_1d."""
    rows = await conn.execute(_VIEW, {"sid": series_id})
    return {r.day: (float(r.energy_wh), int(r.covered_minutes), int(r.n)) for r in rows}


def percentile(sorted_values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in 0..100) of an already sorted list."""
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def compare(exact: dict, view: dict, gate_pct: float = 1.0, min_coverage: float = 0.95) -> dict:
    """Error statistics of the view against the exact value, per day-class.

    Days are classified by the VIEW's coverage (covered_minutes / 1440). Relative error is
    |view - exact| / exact in percent. Also counts days whose covered_minutes differs from the
    independent minute count of the raw data.
    """
    hi, lo = [], []  # (rel_err_pct, day, exact, view, coverage)
    minute_mismatch = 0
    for day, (ev, cov_min, _n) in sorted(view.items()):
        if day not in exact:
            continue
        ex, good_min = exact[day]
        if cov_min != good_min:
            minute_mismatch += 1
        err = abs(ev - ex) / ex * 100 if ex else (0.0 if ev == 0 else float("inf"))
        (hi if cov_min / 1440 >= min_coverage else lo).append((err, day, ex, ev, cov_min / 1440))

    def stats(items):
        errs = sorted(e for e, *_ in items)
        return {
            "days": len(items),
            "err_pct_p50": percentile(errs, 50),
            "err_pct_p95": percentile(errs, 95),
            "err_pct_p99": percentile(errs, 99),
            "err_pct_max": errs[-1] if errs else None,
            "days_over_gate": sum(1 for e in errs if e > gate_pct),
            "worst": [
                {"day": d.isoformat(), "exact_wh": x, "view_wh": v, "coverage": c, "err_pct": e}
                for e, d, x, v, c in sorted(items, key=lambda t: -t[0])[:5]
            ],
        }

    return {
        "full_coverage": stats(hi),
        "low_coverage": stats(lo),
        "covered_minutes_mismatch_days": minute_mismatch,
        "view_days_without_exact": sorted(
            d.isoformat() for d in view if d not in exact
        )[:10],
    }
