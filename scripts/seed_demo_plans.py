"""Past savings plans for a demo home's owner, so a demo guest sees a plan history from the data.

For each of the last --cycles ended billing cycles: the actions are the home's device advice as
it stood at the cycle's start; the days are measured as a live plan's are (`measure_days`), by a
model that learnt only the 365 days before the start (as scripts/backtest_expect.py), with its
out-of-sample daily error as sigma and bias. The REFIT household never followed these plans, so
the verdicts are what the data says. Re-running replaces the owner's `holdout-%` plans.

    docker compose exec -T api python -m scripts.seed_demo_plans --house 5 --cycles 3
"""

import argparse
import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import delete, select, text

from app.database import SessionLocal
from app.modules.billing.api import device_forecasts, forecast_bill
from app.modules.billing.services.bill import ICT, _add_month, _cycle_start, _local_midnight
from app.modules.expect.api import excluded_hours, feature_frame, hourly_actual
from app.modules.expect.services.train import eligible, fit
from app.modules.home.api import HomeMember
from app.modules.insight.models import SavingsPlan
from app.modules.insight.services.plans import freeze_days, measure_days, model_error
from scripts import refit

MAX_ACTIONS = 3
LABELS = {
    "fewer_runs": "Bớt số lần chạy {name}",
    "kettle_fill": "Chỉ đun lượng nước cần dùng",
    "fridge_check": "Kiểm tra gioăng và nhiệt độ {name}",
    "heater_setpoint": "Hạ nhiệt độ đặt {degrees:g}°C",
    "heater_earlier_off": "Tắt sưởi sớm {hours:g} giờ vào buổi tối",
}


async def replace_plans(s, home_id, owner, plans: list[SavingsPlan]) -> bool:
    """Swap the owner's `holdout-%` plans of the home for `plans`; with none built, keep the old
    ones (a re-run without usable data must not empty the demo history)."""
    if not plans:
        return False
    await s.execute(
        delete(SavingsPlan).where(
            SavingsPlan.home_id == home_id,
            SavingsPlan.user_id == owner,
            SavingsPlan.model_version.like("holdout-%"),
        )
    )
    s.add_all(plans)
    return True


async def _holdout(s, home, start: date):
    """A model fitted on the 365 days before `start` only, or None without enough of them."""
    origin = _local_midnight(start)
    lo = origin - timedelta(days=365)
    y = await hourly_actual(s, home.id, lo, origin)
    y[(await excluded_hours(s, home.id, lo, origin)).reindex(y.index, fill_value=False)] = np.nan
    if not eligible(y, home.timezone):
        return None
    x = await feature_frame(s, home.id, y.index[0], origin, origin)
    return await asyncio.to_thread(fit, x, y, version=f"holdout-{start}", tz=home.timezone)


async def main(key: str, cycles: int) -> None:
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
        owner = await s.scalar(
            select(HomeMember.user_id)
            .where(HomeMember.home_id == home.id, HomeMember.role == "owner")
            .limit(1)
        )
        built: list[SavingsPlan] = []
        now = datetime.now(UTC)
        start = _cycle_start(now.astimezone(ICT).date(), home.cd)
        for _ in range(cycles):
            start = _cycle_start(start - timedelta(days=1), home.cd)
            end = _add_month(start) - timedelta(days=1)
            at = _local_midnight(start)
            bundle = await _holdout(s, home, start)
            forecast = await forecast_bill(s, home.id, at)
            advice = await device_forecasts(s, home.id, at)
            if bundle is None or forecast is None or advice is None:
                print(f"{start}: not enough data, skipped")
                continue
            picks = sorted(
                ((d, a) for d in advice.devices for a in d.advice),
                key=lambda da: -da[1].saved_amount,
            )[:MAX_ACTIONS]
            if not picks:
                print(f"{start}: no advice at the start, skipped")
                continue
            span = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            totals = await measure_days(s, home.id, bundle, start, span, now)
            sigma, bias = model_error(bundle.residuals)
            built.append(
                SavingsPlan(
                    user_id=owner,
                    home_id=home.id,
                    start_on=start,
                    end_on=end,
                    model_version=bundle.version,
                    sigma=None if sigma is None else Decimal(str(sigma)),
                    bias=Decimal(str(bias)),
                    forecast_kwh=forecast.kwh,
                    actions=[
                        {
                            "device_id": str(d.device_id),
                            "key": a.key,
                            "label": LABELS[a.key].format(name=d.name, **a.params),
                            "kwh": round(float(a.saved_kwh), 2),
                            "amount": round(float(a.saved_amount)),
                            "baseline": float(d.explain.usual_kwh_day) if d.explain else None,
                            "watts": None,
                        }
                        for d, a in picks
                    ],
                    days=freeze_days({}, totals, bias),
                    status="stopped",
                    created_at=at,
                    stopped_at=_local_midnight(end + timedelta(days=1)),
                )
            )
            saved = sum(t["expected"] + bias * t["n"] / 24 - t["actual"] for t in totals.values())
            print(f"{start}–{end}: {len(totals)} days, {saved:+.1f} kWh against expected")
        if not await replace_plans(s, home.id, owner, built):
            print("no cycle could be rebuilt: the stored plans are kept")
        await s.commit()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--house", required=True)
    p.add_argument("--cycles", type=int, default=3)
    a = p.parse_args()
    asyncio.run(main(a.house, a.cycles))
