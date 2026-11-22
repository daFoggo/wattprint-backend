import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.expect.api import Bundle, active_bundle, expected
from app.modules.home.api import Home
from app.modules.ops.api import scenarios_between

from .bill import ICT, _amounts, _cycle_start, _local_midnight, _price, _round

MODEL_VERSION = "weekday-profile-v1"
PROFILE_DAYS = 28  # whole days the profile looks back over
MIN_DAYS = 7  # fewer usable days than this: no forecast
FULL_DAY_MIN = 0.9 * 24 * 60  # a day counts when the meter reported 90 % of it
GROUP_KEYS = ("weather", "calendar", "occupancy", "trend")
CHANGE_MIN_SHARE = Decimal("0.02")  # "why it changed" shows from 2 % or 10.000 đ
CHANGE_MIN_VND = Decimal(10000)
MIN_COVER = 0.9  # share of the cycle's remaining hours the model must have expected
DRAWS = 2000


@dataclass
class TierCross:
    tier_no: int
    from_kwh: Decimal
    price_per_kwh: Decimal
    on: date  # the day the cycle's kWh passes from_kwh
    probability: float | None = None  # share of the model's draws that pass it (context only)


@dataclass
class Change:
    amount: Decimal  # VND against yesterday's forecast
    parts: dict[str, Decimal]  # used, weather, calendar, occupancy, trend, unexplained


@dataclass
class Accuracy:
    source: str  # "cycle": a closed cycle's mid-cycle forecast; "backtest": the model's own trial
    error_pct: float
    cycles: int


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
    method: str = "weekday"  # "context": the expected-usage model; "weekday": the fallback
    model_version: str = MODEL_VERSION
    kwh_p10: Decimal | None = None
    kwh_p50: Decimal | None = None
    kwh_p90: Decimal | None = None
    amount_p10: Decimal | None = None
    amount_p90: Decimal | None = None
    change: Change | None = None
    accuracy: Accuracy | None = None
    simulated: list[str] | None = None  # active simulated scenarios (heater, demo events)
    drivers: dict | None = None  # what the snapshot keeps to explain tomorrow's change


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


def cycle_end_draws(
    kwh_now: float,
    p50_days: list[float],
    residuals: list[float],
    draws: int = DRAWS,
    seed: int = 7,
    today_share: float = 1.0,
) -> np.ndarray:
    """The cycle's kWh at its end, `draws` times: today's kWh plus each remaining day's expected
    kWh and one of the model's past daily errors drawn at random (today's scaled by the share of
    it still ahead). Seeded, so a page shows the same range on every load."""
    base = kwh_now + sum(p50_days)
    if not residuals or not p50_days:
        return np.full(draws, base)
    rng = np.random.default_rng(seed)
    sample = rng.choice(np.asarray(residuals, dtype=float), size=(draws, len(p50_days)))
    weights = np.ones(len(p50_days))
    weights[0] = today_share
    return base + (sample * weights).sum(axis=1)


def cross_probability(draws: np.ndarray, from_kwh: Decimal) -> float:
    return float(np.mean(draws > float(from_kwh)))


def change_parts(
    snapshot: dict, today: dict, today_iso: str, price: Decimal, amount_change: Decimal
) -> dict[str, Decimal] | None:
    """Split a forecast's change since a snapshot of the same model version (VND): `used` is the
    kWh expected by tonight now against what the snapshot expected by tonight (what was used and
    today's rest), each group the change of its contributions over the days after today, and
    `unexplained` the rest (tiers, rounding). None when the versions differ."""
    if not snapshot or snapshot.get("version") != today.get("version"):
        return None
    tonight_now = today["kwh_now"] + today["p50_daily"].get(today_iso, 0.0)
    tonight_then = snapshot["kwh_now"] + sum(
        v for d, v in snapshot["p50_daily"].items() if d <= today_iso
    )
    kwh = {"used": tonight_now - tonight_then}
    for g in GROUP_KEYS:
        kwh[g] = sum(
            today["groups_daily"][d][g] - snapshot["groups_daily"][d][g]
            for d in today["groups_daily"]
            if d > today_iso and d in snapshot["groups_daily"]
        )
    parts = {k: _round(Decimal(str(v)) * price) for k, v in kwh.items()}
    parts["unexplained"] = amount_change - sum(parts.values(), Decimal(0))
    return parts


async def _snapshot_before(session: AsyncSession, home_id: uuid.UUID, today: date):
    """The latest forecast kept on the day before today (the insight worker keeps one a day)."""
    return (
        await session.execute(
            text(
                "SELECT amount, drivers FROM public.tb_forecast_snapshot WHERE home_id = :h "
                "AND generated_at >= :a AND generated_at < :b AND drivers IS NOT NULL "
                "ORDER BY generated_at DESC LIMIT 1"
            ),
            {
                "h": home_id,
                "a": _local_midnight(today - timedelta(days=1)),
                "b": _local_midnight(today),
            },
        )
    ).first()


async def _accuracy(session: AsyncSession, home_id: uuid.UUID, b: Bundle | None) -> Accuracy | None:
    """The last closed cycle against its forecast nearest mid-cycle; else the model's backtest."""
    row = (
        await session.execute(
            text(
                "SELECT s.amount AS forecast, b.amount_total AS actual FROM public.tb_bill b "
                "JOIN public.tb_forecast_snapshot s ON s.home_id = b.home_id "
                "AND s.horizon_date = b.period_end "
                "WHERE b.home_id = :h AND b.status = 'closed' AND b.amount_total > 0 "
                "ORDER BY b.period_end DESC, abs(extract(epoch FROM s.generated_at - "
                "(b.period_start + (b.period_end - b.period_start) / 2)::timestamptz)) LIMIT 1"
            ),
            {"h": home_id},
        )
    ).first()
    if row is not None:
        err = abs(float(row.forecast) - float(row.actual)) / float(row.actual)
        return Accuracy("cycle", round(err, 4), 1)
    backtest = (b.metrics.get("backtest") if b else None) or {}
    if "mape_ctx" in backtest:
        return Accuracy("backtest", float(backtest["mape_ctx"]), int(backtest.get("cycles", 0)))
    return None


async def _context(
    session: AsyncSession, home_id: uuid.UUID, now: datetime, bill: dict, segments, b: Bundle
) -> dict | None:
    """kWh path, spread and drivers from the model's expected hours; None when it has not
    expected enough of the cycle's remaining hours."""
    end = _local_midnight(bill["period_end"] + timedelta(days=1))
    hour0 = now.replace(minute=0, second=0, microsecond=0)
    frame = await expected(session, home_id, hour0, end)
    need = int((end - hour0).total_seconds() // 3600)
    if need <= 0 or len(frame) < MIN_COVER * need:
        return None
    weight = np.ones(len(frame))
    if len(frame) and frame.index[0] == hour0:
        weight[0] = 1 - (now - hour0).total_seconds() / 3600  # the running hour's rest
    day = [d.isoformat() for d in frame.index.tz_convert(ICT).date]
    p50 = frame["p50"].to_numpy() * weight
    p50_daily: dict[str, float] = {}
    groups_daily: dict[str, dict[str, float]] = {}
    for i, d in enumerate(day):
        p50_daily[d] = p50_daily.get(d, 0.0) + float(p50[i])
        g = groups_daily.setdefault(d, dict.fromkeys(GROUP_KEYS, 0.0))
        for k in GROUP_KEYS:
            g[k] += float(frame[f"c_{k}"].iloc[i] * weight[i])
    today_iso = now.astimezone(ICT).date().isoformat()
    today_share = (
        min(
            1.0, p50_daily.get(today_iso, 0.0) / max(1e-9, sum(p50_daily.values())) * len(p50_daily)
        )
        if today_iso in p50_daily
        else 1.0
    )
    kwh_now = bill["kwh_total"]
    draws = cycle_end_draws(
        float(kwh_now), list(p50_daily.values()), b.residuals, today_share=today_share
    )
    return {
        "p50_daily": p50_daily,
        "groups_daily": groups_daily,
        "draws": draws,
        "kwh": _round(kwh_now + Decimal(str(sum(p50_daily.values()))), "0.001"),
        "drivers": {
            "version": b.version,
            "kwh_now": float(kwh_now),
            "p50_daily": p50_daily,
            "groups_daily": groups_daily,
        },
    }


async def forecast_bill(
    session: AsyncSession, home_id: uuid.UUID, now: datetime | None = None
) -> Forecast | None:
    """The running cycle's bill at its end: from the home's expected-usage model (weather,
    calendar, routine) when it has one, else the usual weekday pattern. None when neither has
    enough full days of readings."""
    now = now or datetime.now(UTC)
    home = await session.get(Home, home_id)
    today = now.astimezone(ICT).date()
    start = _cycle_start(today, home.billing_cycle_day or 1)
    bill, segments, _ = await _price(session, home_id, start, now)
    b = await active_bundle(session, home_id)
    ctx = await _context(session, home_id, now, bill, segments, b) if b else None
    if ctx is None:
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
        draws, basis = None, len(history)
    else:
        cum, path = bill["kwh_total"], []
        for d, v in ctx["p50_daily"].items():
            cum += Decimal(str(v))
            path.append((date.fromisoformat(d), cum))
        kwh, draws = ctx["kwh"], ctx["draws"]
        basis = int(b.metrics.get("days", 0))

    def amount(k: Decimal) -> Decimal:
        before_vat, vat = _amounts(segments, k)
        return before_vat + vat

    # Tiers of the tariff in force today, as the running bill places the kWh.
    tiers = sorted([s for s in segments if s.start <= today][-1].tiers, key=lambda t: t.tier_no)
    ends_in = [t for t in tiers if kwh > t.from_kwh][-1:] or tiers[:1]
    now_kwh = bill["kwh_total"]
    # At exactly from_kwh the next kWh is already in that tier (as current_bill places it).
    upcoming = next((t for t in tiers if t.from_kwh > now_kwh), None)
    cross = None
    if upcoming is not None:
        on = next((d for d, c in path if c > upcoming.from_kwh), None)
        if on is not None:
            cross = TierCross(
                upcoming.tier_no,
                upcoming.from_kwh,
                upcoming.price_per_kwh,
                on,
                None if draws is None else cross_probability(draws, upcoming.from_kwh),
            )
    total = amount(kwh)
    if draws is None:
        low = high = kwh
    else:
        p10, p90 = np.percentile(draws, [10, 90])
        low = min(kwh, _round(Decimal(str(p10)), "0.001"))
        high = max(kwh, _round(Decimal(str(p90)), "0.001"))
    change = None
    if ctx is not None and kwh > 0:
        snap = await _snapshot_before(session, home_id, today)
        if snap is not None:
            moved = total - Decimal(snap.amount)
            if abs(moved) >= min(CHANGE_MIN_VND, CHANGE_MIN_SHARE * Decimal(snap.amount)):
                parts = change_parts(
                    snap.drivers, ctx["drivers"], today.isoformat(), total / kwh, moved
                )
                change = Change(moved, parts) if parts is not None else None
    active = await scenarios_between(session, home_id, now, now)
    return Forecast(
        period_start=start,
        period_end=bill["period_end"],
        kwh=kwh,
        amount=total,
        tier_no=ends_in[0].tier_no,
        next=cross,
        basis_days=basis,
        as_of=today,
        method="weekday" if ctx is None else "context",
        model_version=MODEL_VERSION if ctx is None else b.version,
        kwh_p10=low,
        kwh_p50=kwh,
        kwh_p90=high,
        amount_p10=amount(low),
        amount_p90=amount(high),
        change=change,
        accuracy=await _accuracy(session, home_id, b),
        simulated=sorted({sc.name for sc in active}),
        drivers=None if ctx is None else ctx["drivers"],
    )
