import uuid
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.energy.api import on_w, weather_inputs
from app.modules.ops.api import scenarios_between

from . import calendar

GROUPS: dict[str, tuple[str, ...]] = {
    "weather": (
        "temp_c",
        "temp_24h",
        "temp_72h",
        "humidity_pct",
        "apparent_c",
        "cloud_pct",
        "radiation_wm2",
        "precip_mm",
        "is_day",
    ),
    "calendar": ("hour", "weekday", "holiday"),
    "occupancy": ("presence",),
    "trend": ("base_7d",),
}
FEATURES = tuple(f for g in GROUPS.values() for f in g)
# Switched on by a person: when one runs, someone is home (NILM device types).
HUMAN = ("kettle", "microwave", "toaster", "washing_machine", "dishwasher")
FULL_HOUR_MIN = 54  # an hour counts when the meter reported 90 % of it
FULL_DAY_MIN = 0.9 * 24 * 60
WEEK = pd.Timedelta(days=7)
ROUTINE_WEEKS = 4  # presence: the same weekday-hour over the 4 weeks before


def calendar_frame(index: pd.DatetimeIndex, tz: str, shift_days: int | None) -> pd.DataFrame:
    """hour and weekday on the home's clock; holiday on the recording's date for a demo home."""
    local = index.tz_convert(tz)
    holiday = (
        [int(calendar.is_holiday(calendar.source_date(d, shift_days))) for d in local.date]
        if shift_days is not None
        else [0] * len(index)
    )
    return pd.DataFrame(
        {"hour": local.hour, "weekday": local.day_of_week, "holiday": holiday}, index=index
    )


def presence_frame(active: pd.Series, index: pd.DatetimeIndex, now: pd.Timestamp) -> pd.Series:
    """Share of the same weekday-hour, over the 4 weeks before, when someone was active: the
    routine, never the hour's own activity (it would explain the very usage it sits in). An hour
    not yet known (after `now`) stands in with its own routine."""
    known = {ts: float(v) for ts, v in active.items() if ts < now and not pd.isna(v)}
    out: dict[pd.Timestamp, float] = {}
    for t in sorted(index):
        vals = []
        for k in range(1, ROUTINE_WEEKS + 1):
            u = t - k * WEEK
            v = known.get(u) if u < now else out.get(u, routine(u, known, out, now))
            if v is not None and not np.isnan(v):
                vals.append(v)
        out[t] = float(np.mean(vals)) if vals else np.nan
    return pd.Series(out).reindex(index)


def routine(u: pd.Timestamp, known: dict, done: dict, now: pd.Timestamp) -> float:
    vals = [
        known.get(u - k * WEEK) if u - k * WEEK < now else done.get(u - k * WEEK)
        for k in range(1, ROUTINE_WEEKS + 1)
    ]
    vals = [v for v in vals if v is not None and not np.isnan(v)]
    return float(np.mean(vals)) if vals else np.nan


def base_frame(daily: pd.Series, index: pd.DatetimeIndex, tz: str, now: pd.Timestamp) -> pd.Series:
    """Mean kWh of the 7 local days before each row's day (full days only); future days keep
    today's value."""
    today = now.tz_convert(tz).date()
    by_day: dict[date, float] = {}
    for d in sorted(set(index.tz_convert(tz).date)):
        ref = min(d, today)
        if ref not in by_day:
            window = daily[(daily.index >= ref - timedelta(days=7)) & (daily.index < ref)]
            by_day[ref] = float(window.mean()) if window.notna().any() else np.nan
        by_day[d] = by_day[ref]
    return pd.Series([by_day[d] for d in index.tz_convert(tz).date], index=index)


async def _main_series(s: AsyncSession, home_id: uuid.UUID):
    return await s.scalar(
        text(
            "SELECT series_id FROM public.tb_series WHERE home_id = :h AND kind = 'main' "
            "AND metric = 'power_w' LIMIT 1"
        ),
        {"h": home_id},
    )


def _hours(lo: datetime, hi: datetime) -> pd.DatetimeIndex:
    return pd.date_range(
        pd.Timestamp(lo).tz_convert("UTC").floor("h"),
        pd.Timestamp(hi).tz_convert("UTC"),
        freq="h",
        inclusive="left",
    )


async def hourly_actual(
    s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime
) -> pd.Series:
    """kWh of the main meter per hour over [lo, hi); NaN where it reported under 54 minutes."""
    index = _hours(lo, hi)
    rows = (
        await s.execute(
            text(
                "SELECT r.bucket, r.energy_wh / 1000 AS kwh, r.covered_minutes AS cov "
                "FROM public.reading_1h r JOIN public.tb_series x USING (series_id) "
                "WHERE x.home_id = :h AND x.kind = 'main' AND x.metric = 'power_w' "
                "AND r.bucket >= :lo AND r.bucket < :hi"
            ),
            {"h": home_id, "lo": index[0] if len(index) else lo, "hi": hi},
        )
    ).all()
    got = {pd.Timestamp(r.bucket): float(r.kwh) for r in rows if (r.cov or 0) >= FULL_HOUR_MIN}
    return pd.Series([got.get(t, np.nan) for t in index], index=index, dtype=float)


async def _daily(s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime, tz: str):
    rows = (
        await s.execute(
            text(
                "SELECT r.bucket, r.energy_wh / 1000 AS kwh, r.covered_minutes AS cov "
                "FROM public.reading_1d r JOIN public.tb_series x USING (series_id) "
                "WHERE x.home_id = :h AND x.kind = 'main' AND x.metric = 'power_w' "
                "AND r.bucket >= :lo AND r.bucket < :hi"
            ),
            {"h": home_id, "lo": lo, "hi": hi},
        )
    ).all()
    return pd.Series(
        {
            pd.Timestamp(r.bucket).tz_convert(tz).date(): (
                float(r.kwh) if (r.cov or 0) >= FULL_DAY_MIN else np.nan
            )
            for r in rows
        },
        dtype=float,
    )


async def _activity(s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime) -> pd.Series:
    """Per hour: was a person-operated device on (its peak over its on-threshold)? Hours NILM has
    not analysed are missing, not False."""
    rows = (
        await s.execute(
            text(
                "SELECT e.bucket, d.device_type_code AS code, e.max_w "
                "FROM public.device_estimate_1h e JOIN public.tb_series x USING (series_id) "
                "JOIN public.tb_device d ON d.id = x.device_id "
                "WHERE x.home_id = :h AND e.bucket >= :lo AND e.bucket < :hi"
            ),
            {"h": home_id, "lo": lo, "hi": hi},
        )
    ).all()
    seen: dict[pd.Timestamp, bool] = {}
    for r in rows:
        t = pd.Timestamp(r.bucket)
        on = r.code in HUMAN and float(r.max_w) >= on_w(r.code)
        seen[t] = seen.get(t, False) or on
    return pd.Series(seen, dtype=bool)


async def activity_ratio(s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime) -> float:
    """Hours someone was active over [lo, hi) against the routine for those hours (1 = as usual,
    above 1 = busier than usual: guests, a day at home)."""
    index = _hours(lo, hi)
    if not len(index):
        return 1.0
    active = await _activity(s, home_id, index[0] - (ROUTINE_WEEKS + 1) * WEEK, hi)
    expected = presence_frame(active, index, index[0]).sum()
    seen = active.reindex(index).fillna(False).astype(float).sum()
    if expected <= 0:
        return 2.0 if seen > 0 else 1.0
    return float(seen / expected)


async def excluded_hours(
    s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime
) -> pd.Series:
    """True for the hours inside a demo event (train = false): kept out of training and scoring."""
    index = _hours(lo, hi)
    out = pd.Series(False, index=index)
    for sc in await scenarios_between(s, home_id, lo, hi):
        if sc.train:
            continue
        end = pd.Timestamp(sc.ends_at) if sc.ends_at else index[-1] + pd.Timedelta(hours=1)
        out[(index >= pd.Timestamp(sc.starts_at).floor("h")) & (index < end)] = True
    return out


async def feature_frame(
    s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime, now: datetime
) -> pd.DataFrame:
    """The model's inputs for each hour of [lo, hi) as known at `now`, columns FEATURES."""
    index = _hours(lo, hi)
    now_ = pd.Timestamp(now).tz_convert("UTC")
    tz = await s.scalar(text("SELECT timezone FROM public.tb_home WHERE id = :h"), {"h": home_id})
    shift = await calendar.shift_days(s, home_id)
    weather = await weather_inputs(s, home_id, index[0] - pd.Timedelta(hours=72), hi, now)
    temp = weather["temp_c"]
    frame = weather.reindex(index).copy()
    frame["temp_24h"] = temp.rolling(24, min_periods=12).mean().reindex(index)
    frame["temp_72h"] = temp.rolling(72, min_periods=36).mean().reindex(index)
    frame = frame.join(calendar_frame(index, tz, shift))
    active = await _activity(
        s, home_id, index[0] - (ROUTINE_WEEKS + 1) * WEEK, min(pd.Timestamp(hi), now_)
    )
    frame["presence"] = presence_frame(active, index, now_)
    daily = await _daily(
        s, home_id, index[0] - pd.Timedelta(days=9), now_ + pd.Timedelta(days=1), tz
    )
    frame["base_7d"] = base_frame(daily, index, tz, now_)
    return frame[list(FEATURES)].astype(float)
