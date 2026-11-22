"""Backtest the expected-usage model against the weekday profile on a demo home's own past.

Weekly origins over the last --days: at each, the model learns only what came before it (demo
events left out), then every day of that week forecasts its cycle's end with the kWh used so far,
like the live forecast at local midnight. Only cycles already ended are scored. The result goes
into the active model's metrics (shown as the forecast's accuracy) and is printed.

    docker compose exec -T api python -m scripts.backtest_expect --house 2 --days 182
"""

import argparse
import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import text

from app.database import SessionLocal
from app.modules.billing.services.bill import ICT, _cycle_start, _local_midnight
from app.modules.billing.services.forecast import PROFILE_DAYS, cycle_end_draws, project
from app.modules.expect.api import excluded_hours, feature_frame, hourly_actual, predict
from app.modules.expect.services.train import eligible, fit
from scripts import refit


def score(rows: list[tuple[float, float, float, bool]]) -> dict:
    """rows: (actual end kWh, weekday forecast, model P50, actual inside the model's P10–P90)."""
    if not rows:
        return {"points": 0}
    a = np.array([r[0] for r in rows])
    return {
        "mape_v1": float(np.mean(np.abs(np.array([r[1] for r in rows]) - a) / a)),
        "mape_ctx": float(np.mean(np.abs(np.array([r[2] for r in rows]) - a) / a)),
        "coverage": float(np.mean([r[3] for r in rows])),
        "points": len(rows),
    }


def _period_end(start: date) -> date:
    nxt = date(start.year + (start.month == 12), start.month % 12 + 1, start.day)
    return nxt - timedelta(days=1)


async def main(key: str, days: int) -> None:
    house = int(key.split("-")[0])
    async with SessionLocal() as s:
        home = (
            await s.execute(
                text(
                    "SELECT h.id, h.timezone, coalesce(h.billing_cycle_day, 1) AS cd "
                    "FROM public.tb_meter m JOIN public.tb_home h ON h.id = m.home_id "
                    "WHERE m.serial = :m"
                ),
                {"m": refit.meter(house, key)},
            )
        ).first()
        if home is None:
            raise SystemExit(f"no demo home {key}")
        now = datetime.now(UTC)
        today = _local_midnight(now.astimezone(ICT).date())
        lo = today - timedelta(days=days + 400)
        actual = await hourly_actual(s, home.id, lo, today)
        actual[
            (await excluded_hours(s, home.id, lo, today)).reindex(actual.index, fill_value=False)
        ] = np.nan
        rows, cycles = [], set()
        for k in range(days // 7):
            origin = today - timedelta(days=days - 7 * k)
            hist = actual[(actual.index >= origin - timedelta(days=365)) & (actual.index < origin)]
            if not eligible(hist, home.timezone):
                continue
            x = await feature_frame(s, home.id, hist.index[0], origin, origin)
            b = await asyncio.to_thread(fit, x, hist, version="backtest", tz=home.timezone)
            for d in range(7):
                t = origin + timedelta(days=d)
                day = t.astimezone(ICT).date()
                start = _cycle_start(day, home.cd)
                end = _period_end(start)
                end_ts = _local_midnight(end + timedelta(days=1))
                if end_ts > today:
                    continue
                cycle = actual[(actual.index >= _local_midnight(start)) & (actual.index < end_ts)]
                # REFIT has recording gaps: score a cycle with 70 % of its hours, on those only.
                if cycle.isna().mean() > 0.3:
                    continue
                so_far = float(cycle[cycle.index < t].sum())
                real = float(cycle.sum())
                daily = actual[
                    (actual.index >= t - timedelta(days=PROFILE_DAYS)) & (actual.index < t)
                ]
                by_day = daily.groupby(daily.index.tz_convert(home.timezone).date).agg(
                    ["sum", "count"]
                )
                history = {
                    dd: Decimal(str(r["sum"])) for dd, r in by_day.iterrows() if r["count"] >= 22
                }
                if len(history) < 7:
                    continue
                rest = cycle[cycle.index >= t]
                known = rest.notna()
                share = float(known.mean()) if len(rest) else 1.0
                v1_end = float(project(Decimal(str(so_far)), t, end, history)[-1][1])
                v1 = so_far + (v1_end - so_far) * share  # the weekday path over the measured hours
                p = predict(b, await feature_frame(s, home.id, t, end_ts, t))
                p = p[known.reindex(p.index, fill_value=False)]
                p50 = p["p50"].groupby(p.index.tz_convert(home.timezone).date).sum()
                draws = cycle_end_draws(so_far, p50.tolist(), b.residuals)
                low, high = np.percentile(draws, [10, 90])
                rows.append((real, v1, so_far + float(p50.sum()), bool(low <= real <= high)))
                cycles.add(end)
            print(f"origin {origin:%Y-%m-%d}: {len(rows)} points so far", flush=True)
    result = {**score(rows), "cycles": len(cycles), "ran_at": now.isoformat(timespec="seconds")}
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "UPDATE public.tb_expect_model SET metrics = metrics || "
                "jsonb_build_object('backtest', CAST(:m AS jsonb)) WHERE home_id = :h AND active"
            ),
            {"h": home.id, "m": json.dumps(result)},
        )
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--house", required=True)
    p.add_argument("--days", type=int, default=182)
    a = p.parse_args()
    asyncio.run(main(a.house, a.days))
