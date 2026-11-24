import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.energy.api import weather_inputs
from app.modules.expect.api import FACTOR_MIN_SHARE, PAST_DAYS, device_outlook, feature_frame
from app.modules.home.api import Home
from app.modules.ops.api import HEATER, heater_w, scenarios_between

from .bill import ICT, _amounts, _cycle_start, _local_midnight, _price
from .forecast import forecast_bill

DAYS_AHEAD = 7
RUN_WEEKS = 4  # how often a device runs: its runs of the last 4 weeks
KETTLE_SAVING = Decimal("0.3")  # boiling only the water needed saves about a third of each boil
HEATER_SETPOINT_DOWN = 2.0  # °C
FEWER_RUNS_FROM = 2  # runs a week from which "one fewer a week" is advice
PROGRAM_GAP = timedelta(minutes=60)  # NILM cuts one wash into pieces (its heating phases)
# A joined run under 300 Wh is no wash: NILM's false starts (dozens a week on REFIT). shortcut:
# one threshold for washers and dishwashers; per type once NILM's run detection is measured.
PROGRAM_MIN_WH = 300.0
# One computation per home per hour, shared by the device page, Statistics and Wappi (each takes
# seconds of LightGBM). shortcut: per process and unbounded by homes; move it to the insight
# worker's hourly job (a stored table) when there are more than a few dozen homes.
_CACHE: dict[uuid.UUID, tuple[datetime, DeviceForecasts | None]] = {}


@dataclass
class Day:
    date: date
    kwh: Decimal | None
    kwh_p10: Decimal | None
    kwh_p90: Decimal | None
    amount: Decimal | None


@dataclass
class Advice:
    key: str  # fewer_runs, heater_setpoint, heater_earlier_off, kettle_fill, fridge_check
    saved_kwh: Decimal
    saved_amount: Decimal  # the cycle's bill with it against without it (VAT included)
    avoids_tier: int | None  # the tier the cycle would no longer end in
    params: dict = field(default_factory=dict)  # figures the sentence names


@dataclass
class Factor:
    key: str  # temperature, humidity, sun, rain, calendar, occupancy, trend, other
    kwh_day: Decimal  # what it adds to a day ahead against the device's usual
    amount: Decimal  # that over the 7 days ahead, at the cycle's average price
    now: float | None  # its evidence: the input's mean ahead...
    before: float | None  # ...and over the device's last 28 days
    recent_temp: float | None = None  # trend only: last week's °C when unlike the 28 days'...
    usual_temp: float | None = None  # ...and the 28 days' (the cause of a recent level move)


@dataclass
class Explain:
    """The 7 whole days ahead against the device's usual (its measured daily mean over the last
    28 days); the factors add up to the change (model only: the weekday mean has none)."""

    usual_kwh_day: Decimal
    forecast_kwh_day: Decimal
    explainable: bool  # the model's own past is near the usual: its factors can be trusted
    factors: list[Factor]
    busiest: Day | None  # the day ahead it uses most


@dataclass
class DeviceForecast:
    device_id: uuid.UUID
    name: str
    type: str
    simulated: bool
    method: str  # "model": the device's own model; "weekday": the same weekday-hour mean
    confidence: str  # high, medium, low: the shown method's holdout error
    error_pct: float | None  # that error, mean |daily miss| over mean daily kWh
    backtest_days: int
    next_days: list[Day]
    kwh: Decimal  # to the cycle's end, from now
    kwh_p10: Decimal | None
    kwh_p90: Decimal | None
    amount: Decimal  # its share of the bill at the cycle's average price
    explain: Explain | None  # None before the device has a whole day measured
    advice: list[Advice]


@dataclass
class DeviceForecasts:
    period_end: date
    as_of: date
    devices: list[DeviceForecast]


def _d(x: float | None, q: str = "0.001") -> Decimal | None:
    return None if x is None else Decimal(str(x)).quantize(Decimal(q))


def _explain(e: dict | None, week: list[Day], avg: Decimal) -> Explain | None:
    """The outlook's explanation priced: each shown factor's kWh a day and its VND over the week
    ahead; "other" joins them when it too moves a day by 5 % of the usual."""
    if e is None:
        return None
    lines = list(e["factors"])
    if abs(e["other"]) >= FACTOR_MIN_SHARE * e["usual"] and e["explainable"]:
        lines.append({"key": "other", "kwh_day": e["other"], "now": None, "before": None})
    known = [d for d in week if d.kwh is not None]
    return Explain(
        usual_kwh_day=_d(e["usual"]),
        forecast_kwh_day=_d(e["forecast"]),
        explainable=e["explainable"],
        factors=[
            Factor(
                f["key"],
                _d(f["kwh_day"]),
                (Decimal(str(f["kwh_day"])) * DAYS_AHEAD * avg).quantize(Decimal("1")),
                None if f["now"] is None else round(f["now"], 2),
                None if f["before"] is None else round(f["before"], 2),
                None if f.get("recent_temp") is None else round(f["recent_temp"], 1),
                None if f.get("usual_temp") is None else round(f["usual_temp"], 1),
            )
            for f in lines
        ],
        busiest=max(known, key=lambda d: d.kwh) if known else None,
    )


def _total(days: list[dict], key: str) -> float | None:
    """A range end over the days; None when one day has none."""
    return None if any(x[key] is None for x in days) else sum(x[key] for x in days)


def fewer_runs(runs: int, kwh_per_run: float, days_left: int) -> float | None:
    """kWh saved to the cycle's end by one run fewer a week, for a device run at least twice a
    week over the last 4 weeks; None otherwise."""
    if runs / RUN_WEEKS < FEWER_RUNS_FROM or kwh_per_run <= 0:
        return None
    return kwh_per_run * days_left / 7


def heater_saving(temps: pd.Series, tz: str, params: dict, changed: dict) -> float:
    """kWh the simulated heater would not use over `temps`' hours with `changed` params (the same
    formula the replay adds to the meter)."""
    local = temps.index.tz_convert(tz).hour
    before = sum(heater_w(t, h, params) for t, h in zip(temps, local, strict=True))
    after = sum(heater_w(t, h, {**params, **changed}) for t, h in zip(temps, local, strict=True))
    return (before - after) / 1000


async def _devices(s: AsyncSession, home_id: uuid.UUID):
    return (
        await s.execute(
            text(
                "SELECT id, name, device_type_code AS type FROM public.tb_device "
                "WHERE home_id = :h AND device_type_code <> 'other' AND deleted_at IS NULL "
                "ORDER BY name"
            ),
            {"h": home_id},
        )
    ).all()


def programs(pieces: list[tuple[datetime, datetime, float]]) -> tuple[int, float]:
    """(programs, mean kWh of one): runs NILM found (start, end, Wh) joined when the next starts
    within an hour of the last one's end, since a washer's or dishwasher's program comes out as
    several pieces; a joined run under PROGRAM_MIN_WH is not counted."""
    joined: list[list] = []
    for start, end, wh in sorted(pieces):
        if joined and start - joined[-1][0] <= PROGRAM_GAP:
            joined[-1][0] = max(joined[-1][0], end)
            joined[-1][1] += wh
        else:
            joined.append([end, wh])
    washes = [wh for _, wh in joined if wh >= PROGRAM_MIN_WH]
    return len(washes), (sum(washes) / len(washes) / 1000 if washes else 0.0)


async def _runs(s: AsyncSession, device_id: uuid.UUID, now: datetime) -> tuple[int, float]:
    rows = (
        await s.execute(
            text(
                "SELECT start_ts, end_ts, energy_wh FROM public.tb_device_cycle "
                "WHERE device_id = :d AND start_ts >= :lo AND end_ts <= :now"
            ),
            {"d": device_id, "lo": now - timedelta(weeks=RUN_WEEKS), "now": now},
        )
    ).all()
    return programs([(r.start_ts, r.end_ts, float(r.energy_wh or 0)) for r in rows])


async def _denser_excess(s: AsyncSession, device_id: uuid.UUID) -> float | None:
    """kWh a day an open "cycling denser" alert of the device says it uses over its usual."""
    got = await s.scalar(
        text(
            "SELECT (payload->>'excess_kwh')::float FROM public.tb_alert WHERE device_id = :d "
            "AND kind = 'device_anomaly' AND payload->>'signal' = 'denser' "
            "AND status <> 'resolved' ORDER BY ts DESC LIMIT 1"
        ),
        {"d": device_id},
    )
    return float(got) if got else None


async def device_forecasts(
    s: AsyncSession, home_id: uuid.UUID, now: datetime | None = None
) -> DeviceForecasts | None:
    """Each device's expected kWh and VND for the next 7 days and to the cycle's end, with its
    range, the factor groups behind it (VND), how certain it is, and advice priced against the
    cycle's bill. None when the home has no bill forecast. Computed once per home and hour."""
    now = now or datetime.now(UTC)
    hour = now.replace(minute=0, second=0, microsecond=0)
    cached = _CACHE.get(home_id)
    if cached and cached[0] == hour:
        return cached[1]
    got = await _compute(s, home_id, now)
    _CACHE[home_id] = (hour, got)
    return got


async def _compute(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> DeviceForecasts | None:
    f = await forecast_bill(s, home_id, now)
    if f is None or f.kwh <= 0:
        return None
    home = await s.get(Home, home_id)
    today = now.astimezone(ICT).date()
    _, segments, _ = await _price(s, home_id, _cycle_start(today, home.billing_cycle_day or 1), now)

    def amount(k: Decimal) -> Decimal:
        before_vat, vat = _amounts(segments, max(k, Decimal(0)))
        return before_vat + vat

    tiers = sorted([g for g in segments if g.start <= today][-1].tiers, key=lambda t: t.tier_no)
    avg = f.amount / f.kwh
    hi = _local_midnight(f.period_end + timedelta(days=1))
    lo = pd.Timestamp(now).tz_convert("UTC").floor("h")
    # The devices' inputs, shared: their last 28 days (the usual) to the cycle's end or a week on.
    tomorrow = today + timedelta(days=1)
    home_x = await feature_frame(
        s,
        home_id,
        _local_midnight(today - timedelta(days=PAST_DAYS)),
        max(hi, _local_midnight(tomorrow + timedelta(days=DAYS_AHEAD))),
        now,
    )
    days_left = (f.period_end - today).days + 1
    heaters = [sc for sc in await scenarios_between(s, home_id, now, hi) if sc.name == "heater"]
    temps = (await weather_inputs(s, home_id, lo, hi, now))["temp_c"] if heaters else None

    def priced(key: str, saved_kwh: float | None, **params) -> Advice | None:
        if not saved_kwh or saved_kwh <= 0:
            return None
        kwh = Decimal(str(saved_kwh)).quantize(Decimal("0.001"))
        saved = f.amount - amount(f.kwh - kwh)
        if saved < settings.device_advice_min_vnd:
            return None
        ends_in = [t for t in tiers if f.kwh - kwh > t.from_kwh][-1:] or tiers[:1]
        avoids = f.tier_no if ends_in[0].tier_no < f.tier_no else None
        return Advice(key, kwh, saved.quantize(Decimal("1")), avoids, params)

    out = []
    for d in await _devices(s, home_id):
        o = await device_outlook(s, home_id, d.id, now, hi, home_x)
        if o is None:
            continue
        cycle = [x for x in o["days"] if x["date"] <= f.period_end]
        p50 = sum((x["p50"] or 0) for x in cycle)
        p10, p90 = _total(cycle, "p10"), _total(cycle, "p90")
        week = [
            Day(
                x["date"],
                _d(x["p50"]),
                _d(x["p10"]),
                _d(x["p90"]),
                None if x["p50"] is None else (Decimal(str(x["p50"])) * avg).quantize(Decimal("1")),
            )
            for x in o["days"]
            if tomorrow <= x["date"] < tomorrow + timedelta(days=DAYS_AHEAD)
        ]
        advice: list[Advice | None] = []
        if d.type in ("washing_machine", "dishwasher"):
            n, per_run = await _runs(s, d.id, now)
            advice.append(
                priced(
                    "fewer_runs",
                    fewer_runs(n, per_run, days_left),
                    runs_per_week=round(n / RUN_WEEKS, 1),
                    kwh_per_run=round(per_run, 2),
                )
            )
        elif d.type == "kettle":
            advice.append(priced("kettle_fill", p50 * float(KETTLE_SAVING), share=30))
        elif d.type in ("fridge", "fridge_freezer", "freezer"):
            excess = await _denser_excess(s, d.id)
            advice.append(priced("fridge_check", excess * days_left if excess else None))
        elif d.type == "electric_heater" and heaters and temps is not None:
            params = {**HEATER, **(heaters[-1].params or {})}
            evening = [[a, b - 1] if b >= 20 else [a, b] for a, b in params["hours"]]
            advice += [
                priced(
                    "heater_setpoint",
                    heater_saving(
                        temps,
                        home.timezone,
                        params,
                        {"setpoint_c": params["setpoint_c"] - HEATER_SETPOINT_DOWN},
                    ),
                    degrees=HEATER_SETPOINT_DOWN,
                    setpoint=params["setpoint_c"] - HEATER_SETPOINT_DOWN,
                ),
                priced(
                    "heater_earlier_off",
                    heater_saving(temps, home.timezone, params, {"hours": evening}),
                    hours=1,
                ),
            ]
        out.append(
            DeviceForecast(
                device_id=d.id,
                name=d.name,
                type=d.type,
                simulated=d.type == "electric_heater",
                method=o["method"],
                confidence=o["confidence"],
                error_pct=None if o["wape"] is None else round(100 * o["wape"], 1),
                backtest_days=o["backtest_days"],
                next_days=week,
                kwh=_d(p50),
                kwh_p10=_d(p10),
                kwh_p90=_d(p90),
                amount=(Decimal(str(p50)) * avg).quantize(Decimal("1")),
                explain=_explain(o["explain"], week, avg),
                advice=sorted((a for a in advice if a), key=lambda a: a.saved_amount, reverse=True)[
                    :3
                ],
            )
        )
    out.sort(key=lambda x: x.amount, reverse=True)
    return DeviceForecasts(f.period_end, today, out)
