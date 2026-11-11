import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LADDER = ("1m", "5m", "15m", "30m", "1h", "3h", "6h", "1d")
_STEP = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "3h": timedelta(hours=3),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
}
# step -> (aggregate it reads, whether it is a time_bucket re-bucket of that aggregate)
_SOURCE = {
    "1m": ("reading_1m", False),
    "5m": ("reading_1m", True),
    "15m": ("reading_1m", True),
    "30m": ("reading_1m", True),
    "1h": ("reading_1h", False),
    "3h": ("reading_1h", True),
    "6h": ("reading_1h", True),
    "1d": ("reading_1d", False),
}
MAX_WINDOW = timedelta(days=90)
MAX_POINTS_LIMIT = 2000
LATEST_LOOKBACK = timedelta(days=7)
DEVICE_HOURLY_MAX = timedelta(days=3)
# Local midnight (Asia/Ho_Chi_Minh, UTC+7, no DST) is 17:00 UTC: bucket origin for every step.
ORIGIN = datetime(2000, 1, 1, 17, tzinfo=UTC)


@dataclass
class Point:
    ts: datetime
    avg_w: float
    min_w: float
    max_w: float
    energy_wh: float


@dataclass
class LatestPower:
    ts: datetime
    watts: float


@dataclass
class DeviceEnergy:
    device_id: int
    kwh: float
    share: float


def _require_aware(**values: datetime) -> None:
    for name, value in values.items():
        if value.tzinfo is None:
            raise ValueError(f"{name} must be a timezone-aware datetime")


def _check_window(since: datetime, until: datetime) -> None:
    _require_aware(since=since, until=until)
    if until <= since:
        raise ValueError("until must be after since")


def pick_step(since: datetime, until: datetime, max_points: int) -> str:
    """The finest ladder step whose bucket count ceil((until - since) / step) is <= max_points.

    Falls back to "1d" when even that gives more buckets (a 90 day window at a tiny max_points).
    """
    _check_window(since, until)
    span = until - since
    if span > MAX_WINDOW:
        raise ValueError("window is longer than 90 days")
    if not 1 <= max_points <= MAX_POINTS_LIMIT:
        raise ValueError(f"max_points must be between 1 and {MAX_POINTS_LIMIT}")
    for step in LADDER:
        if math.ceil(span / _STEP[step]) <= max_points:
            return step
    return "1d"


def _floor(ts: datetime, step: timedelta) -> datetime:
    """Start of the step bucket (aligned to local midnight) that contains ts."""
    return ORIGIN + ((ts - ORIGIN) // step) * step


def _ceil(ts: datetime, step: timedelta) -> datetime:
    """First step boundary at or after ts (aligned to local midnight)."""
    return ORIGIN - ((ORIGIN - ts) // step) * step


def _minute(now: datetime | None) -> datetime:
    now = now or datetime.now(UTC)
    _require_aware(now=now)
    return now.replace(second=0, microsecond=0)


async def _main_series(session: AsyncSession, home_id: int) -> int | None:
    return await session.scalar(
        text(
            "SELECT series_id FROM public.tb_series "
            "WHERE home_id = :h AND kind = 'main' AND metric = 'power_w'"
        ),
        {"h": home_id},
    )


async def meter_series(
    session: AsyncSession,
    home_id: int,
    since: datetime,
    until: datetime,
    max_points: int = 600,
    now: datetime | None = None,
) -> list[Point]:
    """The main-meter power series of a home as at most ~max_points points.

    The step comes from `pick_step`; buckets are aligned to local midnight (17:00 UTC).

    The window `[since, until)` is bucket-granular: every bucket whose start lies in
    `[floor(since), until)` is returned whole, never cut at `since` or `until`. The only cap is
    the open-minute rule: for steps 1m/5m/15m/30m (derived from `reading_1m`) data of the minute
    still being written (>= date_trunc('minute', now)) is excluded; steps 1h/3h/6h/1d (derived
    from the 1h/1d real-time views) include real-time data up to the present instant. So the last
    point of any step is partial and moves, and when the step switches from 30m to 1h the content
    of the "current" point can change (it then includes the open minute).

    A re-bucketed `avg_w` is sample-weighted (sum(avg_w * n) / sum(n)), never a mean of means.
    Missing buckets are not filled. Returns [] for a home without a main series or data.
    """
    step = pick_step(since, until, max_points)
    open_minute = _minute(now)
    series_id = await _main_series(session, home_id)
    if series_id is None:
        return []
    view, rebucket = _SOURCE[step]
    params = {
        "sid": series_id,
        "lo": _floor(since, _STEP[step]),
        "hi": _ceil(until, _STEP[step]),  # output bucket starts < until, buckets whole
    }
    if view == "reading_1m":
        params["hi"] = min(params["hi"], open_minute)
    if rebucket:
        sql = (
            "SELECT time_bucket(CAST(:step AS interval), bucket, "
            "origin => CAST(:origin AS timestamptz)) AS ts, "
            "sum(CAST(avg_w AS double precision) * n) / NULLIF(sum(n), 0) AS avg_w, "
            "min(min_w) AS min_w, max(max_w) AS max_w, sum(energy_wh) AS energy_wh "
            f"FROM public.{view} "
            "WHERE series_id = :sid AND bucket >= :lo AND bucket < :hi GROUP BY 1 ORDER BY 1"
        )
        params |= {"step": _STEP[step], "origin": ORIGIN}
    else:
        sql = (
            "SELECT bucket AS ts, avg_w, min_w, max_w, energy_wh "
            f"FROM public.{view} "
            "WHERE series_id = :sid AND bucket >= :lo AND bucket < :hi ORDER BY bucket"
        )
    rows = await session.execute(text(sql), params)
    return [
        Point(r.ts, float(r.avg_w), float(r.min_w), float(r.max_w), float(r.energy_wh))
        for r in rows
    ]


def _latest_statement(series_id: int, now: datetime | None) -> tuple[str, dict]:
    hi = _minute(now)
    sql = (
        "SELECT bucket, last_w FROM public.reading_1m "
        "WHERE series_id = :sid AND bucket >= :lo AND bucket < :hi "
        "ORDER BY bucket DESC LIMIT 1"
    )
    return sql, {"sid": series_id, "lo": hi - LATEST_LOOKBACK, "hi": hi}


async def latest_power(
    session: AsyncSession, home_id: int, now: datetime | None = None
) -> LatestPower | None:
    """The newest closed 1-minute bucket of the main series within the last 7 days."""
    series_id = await _main_series(session, home_id)
    if series_id is None:
        return None
    sql, params = _latest_statement(series_id, now)
    row = (await session.execute(text(sql), params)).first()
    return None if row is None else LatestPower(row.bucket, float(row.last_w))


async def device_breakdown(
    session: AsyncSession, home_id: int, since: datetime, until: datetime
) -> list[DeviceEnergy]:
    """Energy per device of a home over the window, largest first.

    Reads `device_estimate_1h` for windows up to 3 days and `device_estimate_1d` beyond. The
    window is bucket-granular and widened to whole buckets at both ends: every bucket whose start
    lies in `[floor(since), until)` counts, so an unaligned 1-hour window spans two hourly
    buckets. Pass aligned bounds for an exact figure. `share` is relative to the listed devices,
    so shares add up to 1 (all 0 when the devices have no energy). Devices without data are omitted.
    """
    _check_window(since, until)
    series = (
        await session.execute(
            text(
                "SELECT series_id, device_id FROM public.tb_series "
                "WHERE home_id = :h AND kind = 'device' AND metric = 'power_w'"
            ),
            {"h": home_id},
        )
    ).all()
    if not series:
        return []
    daily = until - since > DEVICE_HOURLY_MAX
    view = "device_estimate_1d" if daily else "device_estimate_1h"
    bucket = _STEP["1d" if daily else "1h"]
    lo = _floor(since, bucket)
    by_series = {s.series_id: s.device_id for s in series}
    rows = await session.execute(
        text(
            f"SELECT series_id, sum(energy_wh) AS wh FROM public.{view} "
            "WHERE series_id = ANY(:ids) AND bucket >= :lo AND bucket < :hi GROUP BY series_id"
        ),
        {"ids": list(by_series), "lo": lo, "hi": _ceil(until, bucket)},
    )
    kwh: dict[int, float] = {}
    for r in rows:
        device = by_series[r.series_id]
        kwh[device] = kwh.get(device, 0.0) + float(r.wh) / 1000
    total = sum(kwh.values())
    return [
        DeviceEnergy(d, k, k / total if total > 0 else 0.0)
        for d, k in sorted(kwh.items(), key=lambda e: (-e[1], str(e[0])))
    ]
