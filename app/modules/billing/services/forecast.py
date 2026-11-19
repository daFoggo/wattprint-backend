import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.home.api import Home

from .bill import ICT, _amounts, _cycle_start, _local_midnight, _price, _round

MODEL_VERSION = "weekday-profile-v1"
PROFILE_DAYS = 28  # whole days the profile looks back over
MIN_DAYS = 7  # fewer usable days than this: no forecast
FULL_DAY_MIN = 0.9 * 24 * 60  # a day counts when the meter reported 90 % of it


@dataclass
class TierCross:
    tier_no: int
    from_kwh: Decimal
    price_per_kwh: Decimal
    on: date  # the day the cycle's kWh passes from_kwh


@dataclass
class Forecast:
    period_start: date
    period_end: date
    kwh: Decimal
    amount: Decimal  # VAT included
    tier_no: int  # the tier the cycle ends in
    next: TierCross | None  # the next tier, if this cycle reaches it
    basis_days: int
    as_of: date  # the local day it was made on


async def _daily_kwh(session: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime):
    """kWh per local day of the main meter, only days it reported for 90 % of."""
    rows = await session.execute(
        text(
            "SELECT r.bucket, sum(r.energy_wh) / 1000 AS kwh, sum(r.covered_minutes) AS cov "
            "FROM public.reading_1d r JOIN public.tb_series s USING (series_id) "
            "WHERE s.home_id = :h AND s.kind = 'main' AND s.metric = 'power_w' "
            "AND r.bucket >= :lo AND r.bucket < :hi GROUP BY r.bucket"
        ),
        {"h": home_id, "lo": lo, "hi": hi},
    )
    return {
        r.bucket.astimezone(ICT).date(): Decimal(r.kwh)
        for r in rows
        if r.cov is not None and r.cov >= FULL_DAY_MIN
    }


def project(
    kwh_now: Decimal,
    now: datetime,
    period_end: date,
    history: dict[date, Decimal],
) -> list[tuple[date, Decimal]]:
    """The cycle's running kWh at the end of each day from today to period_end.

    Each day to come uses the mean of past days on the same weekday (the overall mean where a
    weekday has none); today adds that day's mean times the share of it still ahead.
    """
    by_weekday: dict[int, list[Decimal]] = defaultdict(list)
    for d, kwh in history.items():
        by_weekday[d.weekday()].append(kwh)
    overall = sum(history.values(), Decimal(0)) / len(history)
    mean = {wd: sum(v, Decimal(0)) / len(v) for wd, v in by_weekday.items()}

    local = now.astimezone(ICT)
    today = local.date()
    midnight = datetime(today.year, today.month, today.day, tzinfo=ICT)
    ahead = Decimal(1) - Decimal((local - midnight).total_seconds()) / Decimal(86_400)
    path, cum, day = [], kwh_now, today
    while day <= period_end:
        expected = mean.get(day.weekday(), overall)
        cum += expected * ahead if day == today else expected
        path.append((day, cum))
        day += timedelta(days=1)
    return path


async def forecast_bill(
    session: AsyncSession, home_id: uuid.UUID, now: datetime | None = None
) -> Forecast | None:
    """The running cycle's bill at its end if the home keeps its usual weekday pattern.
    None when fewer than MIN_DAYS of the last PROFILE_DAYS have full readings."""
    now = now or datetime.now(UTC)
    home = await session.get(Home, home_id)
    today = now.astimezone(ICT).date()
    start = _cycle_start(today, home.billing_cycle_day or 1)
    bill, segments, _ = await _price(session, home_id, start, now)
    history = await _daily_kwh(
        session,
        home_id,
        _local_midnight(today - timedelta(days=PROFILE_DAYS)),
        _local_midnight(today),
    )
    if len(history) < MIN_DAYS:
        return None
    path = project(bill["kwh_total"], now, bill["period_end"], history)
    kwh = _round(path[-1][1], "0.001")
    before_vat, vat = _amounts(segments, kwh)
    # Tiers of the tariff in force today, as the running bill places the kWh.
    tiers = sorted([s for s in segments if s.start <= today][-1].tiers, key=lambda t: t.tier_no)
    ends_in = [t for t in tiers if kwh > t.from_kwh][-1:] or tiers[:1]
    now_kwh = bill["kwh_total"]
    # At exactly from_kwh the next kWh is already in that tier (as current_bill places it).
    upcoming = next((t for t in tiers if t.from_kwh > now_kwh), None)
    cross = None
    if upcoming is not None:
        on = next((d for d, cum in path if cum > upcoming.from_kwh), None)
        if on is not None:
            cross = TierCross(upcoming.tier_no, upcoming.from_kwh, upcoming.price_per_kwh, on)
    return Forecast(
        period_start=start,
        period_end=bill["period_end"],
        kwh=kwh,
        amount=before_vat + vat,
        tier_no=ends_in[0].tier_no,
        next=cross,
        basis_days=len(history),
        as_of=today,
    )
