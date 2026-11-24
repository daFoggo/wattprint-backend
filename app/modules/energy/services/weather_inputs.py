import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ops.api import scenarios_between

from ..models import HomeWeatherHourly

COLUMNS = (
    "temp_c",
    "humidity_pct",
    "apparent_c",
    "cloud_pct",
    "radiation_wm2",
    "precip_mm",
    "is_day",
)
OBSERVED_AHEAD = timedelta(days=5)  # as far as a weather forecast is trusted
YEAR = timedelta(days=364)  # 52 weeks, the REFIT shift step
NORMAL_DAYS = 7  # the normal: the same hour within ±7 days of the same date a year earlier
RECENT = timedelta(days=14)  # without a year stored: the same hour of the last two weeks


async def _rows(s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime) -> pd.DataFrame:
    rows = (
        await s.execute(
            select(HomeWeatherHourly.ts, *(getattr(HomeWeatherHourly, c) for c in COLUMNS)).where(
                HomeWeatherHourly.home_id == home_id,
                HomeWeatherHourly.ts >= lo,
                HomeWeatherHourly.ts < hi,
            )
        )
    ).all()
    frame = pd.DataFrame(rows, columns=["ts", *COLUMNS])
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame.set_index("ts").astype(float)


async def weather_inputs(
    s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime, now: datetime
) -> pd.DataFrame:
    """The home's hourly weather over [lo, hi) as a model sees it at `now`: observed up to five
    days ahead, the normal beyond (a year earlier, else the last two weeks' same hour); cold-spell
    scenarios lower the temperatures in their window. Observed hours without data are NaN."""
    index = pd.date_range(
        pd.Timestamp(lo).tz_convert(UTC).floor("h"),
        pd.Timestamp(hi).tz_convert(UTC),
        freq="h",
        inclusive="left",
    )
    out = pd.DataFrame(index=index, columns=list(COLUMNS), dtype=float)
    cutoff = pd.Timestamp(now + OBSERVED_AHEAD)
    observed = await _rows(s, home_id, lo, hi)
    observed = observed[observed.index <= cutoff]
    out.update(observed)
    later = index[index > cutoff]
    if len(later):
        span = timedelta(days=NORMAL_DAYS)
        old = await _rows(
            s, home_id, later[0] - YEAR - span, later[-1] - YEAR + span + timedelta(hours=1)
        )
        offsets = [pd.Timedelta(days=d) - YEAR for d in range(-NORMAL_DAYS, NORMAL_DAYS + 1)]
        for ts in later:
            out.loc[ts] = old.reindex([ts + o for o in offsets]).mean()
        # No year stored (a new home, a recording's first year): the same hour of the last two
        # weeks observed, never a gap; a model learnt gaps as their own signal (2 kWh/day).
        gap = later[out.loc[later, "temp_c"].isna()]
        if len(gap):
            recent = await _rows(s, home_id, cutoff - RECENT, cutoff + timedelta(hours=1))
            hourly = recent.groupby(recent.index.hour).mean()
            out.loc[gap] = hourly.reindex(gap.hour).to_numpy()
        out.loc[later, "is_day"] = (out.loc[later, "is_day"] >= 0.5).astype(float)
    for sc in await scenarios_between(s, home_id, lo, hi):
        if sc.name != "cold_spell":
            continue
        end = pd.Timestamp(sc.ends_at) if sc.ends_at else index[-1] + pd.Timedelta(hours=1)
        inside = (index >= pd.Timestamp(sc.starts_at)) & (index < end)
        delta = float(sc.params.get("delta_c", 0))
        out.loc[inside, ["temp_c", "apparent_c"]] -= delta
    return out
