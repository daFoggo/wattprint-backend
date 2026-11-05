"""Read model of the NILM results: per-appliance report (day / week) and the latest minutes.

Energy comes from the continuous aggregates (`energy.reading_1h|_1d` and
`energy.device_estimate_1h|_1d`), like app/services/meter.py. The per-minute accuracy and the
"latest minutes" view read the raw hypertables over small windows (at most one week, or a few
hundred rows).

A "day" is a calendar day of Asia/Ho_Chi_Minh (UTC+7, no DST), the same day the aggregates use.
"""

import datetime as dt
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.disaggregation import (
    BreakdownItem,
    DailyPoint,
    DisaggregationOut,
    HourlyPoint,
    LatestOut,
    LatestPoint,
)

VN = dt.timezone(dt.timedelta(hours=7))  # Asia/Ho_Chi_Minh has no DST
OTHER = "other"


def local_today(now: dt.datetime | None = None) -> dt.date:
    """Today's date in Asia/Ho_Chi_Minh."""
    return (now or dt.datetime.now(dt.UTC)).astimezone(VN).date()


def local_day_start(day: dt.date) -> dt.datetime:
    """The UTC instant at which `day` (Asia/Ho_Chi_Minh) starts."""
    return dt.datetime.combine(day, dt.time.min, tzinfo=VN).astimezone(dt.UTC)


def accuracy_pct(abs_err: float, true_sum: float) -> float | None:
    """100 * (1 - sum|est - true| / (2 * sum true)), clipped to 0..100; None without a signal."""
    if true_sum <= 0:
        return None
    return round(max(0.0, 1 - abs_err / (2 * true_sum)) * 100, 1)


@dataclass(frozen=True)
class Tracked:
    """An appliance of a home that has a model estimate series (and usually a plug sub-meter)."""

    key: str  # catalog.device_type code, made unique within the home
    name: str
    device_id: uuid.UUID
    estimate_series: int
    plug_series: int | None
    channel: str | None


async def home_of(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    """The home of an account (one account, one home), or None."""
    return await db.scalar(
        text("SELECT home_id FROM core.home_member WHERE user_id = :u"), {"u": user_id}
    )


async def main_series(db: AsyncSession, home_id: uuid.UUID) -> int | None:
    return await db.scalar(
        text(
            "SELECT series_id FROM energy.series "
            "WHERE home_id = :h AND kind = 'main' AND metric = 'power_w'"
        ),
        {"h": home_id},
    )


async def tracked_appliances(db: AsyncSession, home_id: uuid.UUID) -> list[Tracked]:
    rows = (
        await db.execute(
            text(
                "SELECT d.id AS device_id, d.device_type_code AS type, d.name, "
                "max(s.series_id) FILTER (WHERE s.kind = 'device') AS estimate_series, "
                "max(s.series_id) FILTER (WHERE s.kind = 'plug') AS plug_series, "
                "max(s.source_channel) FILTER (WHERE s.kind = 'plug') AS channel "
                "FROM energy.series s JOIN core.device d ON d.id = s.device_id "
                "WHERE s.home_id = :h AND s.metric = 'power_w' AND s.kind IN ('plug', 'device') "
                "GROUP BY d.id, d.device_type_code, d.name "
                "HAVING bool_or(s.kind = 'device') ORDER BY d.device_type_code, d.name"
            ),
            {"h": home_id},
        )
    ).all()
    seen: dict[str, int] = defaultdict(int)
    for r in rows:
        seen[r.type] += 1
    return [
        Tracked(
            key=r.type if seen[r.type] == 1 else f"{r.type} ({r.name})",
            name=r.name,
            device_id=r.device_id,
            estimate_series=r.estimate_series,
            plug_series=r.plug_series,
            channel=r.channel,
        )
        for r in rows
    ]


async def report(
    db: AsyncSession, home_id: uuid.UUID, period: str, day: dt.date
) -> DisaggregationOut:
    """Energy per appliance over one local day (hourly points) or seven (daily points)."""
    start = local_day_start(day)
    days = 1 if period == "day" else 7
    end = start + dt.timedelta(days=days)
    step = dt.timedelta(hours=1) if period == "day" else dt.timedelta(days=1)
    reading_view, estimate_view = (
        ("reading_1h", "device_estimate_1h")
        if period == "day"
        else ("reading_1d", "device_estimate_1d")
    )
    window = {"a": start, "b": end}

    tracked = await tracked_appliances(db, home_id)
    main = await main_series(db, home_id)

    total_wh: dict[dt.datetime, float] = defaultdict(float)
    if main is not None:
        rows = await db.execute(
            text(
                f"SELECT bucket, energy_wh FROM energy.{reading_view} "
                "WHERE series_id = :s AND bucket >= :a AND bucket < :b"
            ),
            {"s": main, **window},
        )
        for r in rows:
            total_wh[r.bucket] += float(r.energy_wh)

    est_wh: dict[tuple[int, dt.datetime], float] = defaultdict(float)
    est_ids = [t.estimate_series for t in tracked]
    if est_ids:
        rows = await db.execute(
            text(
                f"SELECT series_id, bucket, energy_wh FROM energy.{estimate_view} "
                "WHERE series_id = ANY(:ids) AND bucket >= :a AND bucket < :b"
            ),
            {"ids": est_ids, **window},
        )
        for r in rows:
            est_wh[(r.series_id, r.bucket)] += float(r.energy_wh)

    true_wh: dict[int, float] = {}
    plug_ids = [t.plug_series for t in tracked if t.plug_series is not None]
    if plug_ids:
        rows = await db.execute(
            text(
                f"SELECT series_id, sum(energy_wh) AS wh FROM energy.{reading_view} "
                "WHERE series_id = ANY(:ids) AND bucket >= :a AND bucket < :b GROUP BY series_id"
            ),
            {"ids": plug_ids, **window},
        )
        true_wh = {r.series_id: float(r.wh) for r in rows}

    total_kwh = sum(total_wh.values()) / 1000
    est_kwh = {
        t.key: sum(v for (sid, _b), v in est_wh.items() if sid == t.estimate_series) / 1000
        for t in tracked
    }
    other_kwh = max(total_kwh - sum(est_kwh.values()), 0.0)

    def pct(value: float) -> float:
        return round(value / total_kwh * 100, 1) if total_kwh > 0 else 0.0

    sum_err = sum_true = 0.0
    breakdown: list[BreakdownItem] = []
    for t in sorted(tracked, key=lambda t: -est_kwh[t.key]):
        item = BreakdownItem(
            appliance=t.key,
            name=t.name,
            device_id=t.device_id,
            kwh=round(est_kwh[t.key], 3),
            percent=pct(est_kwh[t.key]),
        )
        truth = true_wh.get(t.plug_series) if t.plug_series is not None else None
        if truth is not None and truth > 0:
            item.true_kwh = round(truth / 1000, 3)
            item.energy_error_pct = round((est_kwh[t.key] * 1000 - truth) / truth * 100, 1)
            err, true_sum = await _minute_error(db, t, start, end)
            item.accuracy_pct = accuracy_pct(err, true_sum)
            sum_err += err
            sum_true += true_sum
        breakdown.append(item)
    breakdown.append(
        BreakdownItem(appliance=OTHER, kwh=round(other_kwh, 3), percent=pct(other_kwh))
    )

    def split(bucket: dt.datetime) -> tuple[float, dict[str, float]]:
        """(total kWh, kWh per appliance + other) of one bucket; a bucket without data is 0."""
        total = total_wh.get(bucket, 0.0) / 1000
        per = {t.key: est_wh.get((t.estimate_series, bucket), 0.0) / 1000 for t in tracked}
        per[OTHER] = max(total - sum(per.values()), 0.0)
        return round(total, 3), {k: round(v, 3) for k, v in per.items()}

    out = DisaggregationOut(
        home_id=home_id,
        period=period,
        start=start,
        end=end,
        total_kwh=round(total_kwh, 3),
        explained_pct=round((total_kwh - other_kwh) / total_kwh * 100, 1)
        if total_kwh > 0
        else None,
        accuracy_pct=accuracy_pct(sum_err, sum_true),
        breakdown=breakdown,
    )
    buckets = [start + step * i for i in range(int((end - start) / step))]
    if period == "day":
        out.hourly = [
            HourlyPoint(hour=b, total_kwh=split(b)[0], by_appliance=split(b)[1]) for b in buckets
        ]
    else:
        out.daily = [
            DailyPoint(day=b.astimezone(VN).date(), total_kwh=split(b)[0], by_appliance=split(b)[1])
            for b in buckets
        ]
    return out


async def _minute_error(
    db: AsyncSession, t: Tracked, start: dt.datetime, end: dt.datetime
) -> tuple[float, float]:
    """(sum |estimate - sub-meter|, sum sub-meter) in W over the minutes both have a value."""
    row = (
        await db.execute(
            text(
                "SELECT sum(abs(e.value - r.value)) AS err, sum(r.value) AS tru "
                "FROM energy.device_estimate e "
                "JOIN energy.reading r ON r.series_id = :ps AND r.ts = e.ts "
                "WHERE e.series_id = :es AND e.ts >= :a AND e.ts < :b"
            ),
            {"ps": t.plug_series, "es": t.estimate_series, "a": start, "b": end},
        )
    ).one()
    return float(row.err or 0.0), float(row.tru or 0.0)


async def latest(db: AsyncSession, home_id: uuid.UUID, minutes: int) -> LatestOut:
    """The newest `minutes` samples of the main meter with the estimates and sub-meters at them."""
    main = await main_series(db, home_id)
    if main is None:
        return LatestOut(home_id=home_id, points=[])
    rows = (
        await db.execute(
            text(
                "SELECT ts, value FROM energy.reading "
                "WHERE series_id = :s ORDER BY ts DESC LIMIT :n"
            ),
            {"s": main, "n": minutes},
        )
    ).all()
    if not rows:
        return LatestOut(home_id=home_id, points=[])
    rows.reverse()  # oldest first
    t0, t1 = rows[0].ts, rows[-1].ts

    tracked = await tracked_appliances(db, home_id)
    est_key = {t.estimate_series: t.key for t in tracked}
    plug_key = {t.plug_series: t.key for t in tracked if t.plug_series is not None}
    estimates: dict[dt.datetime, dict[str, float]] = defaultdict(dict)
    truths: dict[dt.datetime, dict[str, float]] = defaultdict(dict)
    if est_key:
        result = await db.execute(
            text(
                "SELECT ts, series_id, value FROM energy.device_estimate "
                "WHERE series_id = ANY(:ids) AND ts >= :a AND ts <= :b"
            ),
            {"ids": list(est_key), "a": t0, "b": t1},
        )
        for r in result:
            estimates[r.ts][est_key[r.series_id]] = round(float(r.value), 1)
    if plug_key:
        result = await db.execute(
            text(
                "SELECT ts, series_id, value FROM energy.reading "
                "WHERE series_id = ANY(:ids) AND ts >= :a AND ts <= :b"
            ),
            {"ids": list(plug_key), "a": t0, "b": t1},
        )
        for r in result:
            truths[r.ts][plug_key[r.series_id]] = round(float(r.value), 1)

    points = []
    for r in rows:
        est = estimates.get(r.ts)
        truth = truths.get(r.ts)
        points.append(
            LatestPoint(
                ts=r.ts,
                aggregate_w=round(float(r.value), 1),
                appliances_w=est,
                other_w=round(max(float(r.value) - sum(est.values()), 0.0), 1) if est else None,
                truth_w=truth,
                error_w=(
                    {k: round(truth[k] - est[k], 1) for k in est if k in truth}
                    if est and truth
                    else None
                ),
            )
        )
    return LatestOut(home_id=home_id, points=points)
