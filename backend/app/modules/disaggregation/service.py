from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import BreakdownItem, DailyPoint, DisaggregationOut, HourlyPoint

STEP_SECONDS = 60                       # phải khớp bước resample lúc train/ingest
KWH_PER_WATT_SAMPLE = STEP_SECONDS / 3600 / 1000  # = 1/60000
OTHER = "other"
KNOWN_APPLIANCES = ["kettle", "microwave", "dishwasher", "washing_machine"]

_SQL_BY_APPLIANCE = text("""
    SELECT appliance, SUM(watts) * :k AS kwh
    FROM appliance_power
    WHERE house_id = :h AND ts >= :start AND ts < :end
    GROUP BY appliance
""")
_SQL_AGG_BUCKET = text("""
    SELECT time_bucket(:bucket, ts) AS b, SUM(watts) * :k AS kwh
    FROM aggregate_power
    WHERE house_id = :h AND ts >= :start AND ts < :end
    GROUP BY b
""")
_SQL_APP_BUCKET = text("""
    SELECT time_bucket(:bucket, ts) AS b, appliance, SUM(watts) * :k AS kwh
    FROM appliance_power
    WHERE house_id = :h AND ts >= :start AND ts < :end
    GROUP BY b, appliance
""")


async def get_disaggregation(
    db: AsyncSession, house_id: int, period: str, day: date
) -> DisaggregationOut:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    days = 1 if period == "day" else 7
    end = start + timedelta(days=days)
    bucket = timedelta(hours=1) if period == "day" else timedelta(days=1)
    p = {"h": house_id, "start": start, "end": end, "k": KWH_PER_WATT_SAMPLE}

    by_app = {r.appliance: r.kwh for r in await db.execute(_SQL_BY_APPLIANCE, p)}
    agg_bucket = {r.b: r.kwh for r in await db.execute(_SQL_AGG_BUCKET, {**p, "bucket": bucket})}
    app_bucket: dict[datetime, dict[str, float]] = defaultdict(dict)
    for r in await db.execute(_SQL_APP_BUCKET, {**p, "bucket": bucket}):
        app_bucket[r.b][r.appliance] = r.kwh

    total = sum(agg_bucket.values())
    appliances = sorted(set(KNOWN_APPLIANCES) | set(by_app), key=lambda a: by_app.get(a, 0.0), reverse=True)

    def pct(v: float) -> float:
        return round(v / total * 100, 1) if total > 0 else 0.0

    other = max(total - sum(by_app.values()), 0.0)
    breakdown = [BreakdownItem(appliance=a, kwh=round(by_app.get(a, 0.0), 3), percent=pct(by_app.get(a, 0.0))) for a in appliances]
    breakdown.append(BreakdownItem(appliance=OTHER, kwh=round(other, 3), percent=pct(other)))

    def split(b: datetime) -> tuple[float, dict[str, float]]:
        """(tổng kWh, kWh theo thiết bị + other) của 1 bucket; bucket thiếu dữ liệu = 0."""
        t = agg_bucket.get(b, 0.0)
        per = {a: round(app_bucket.get(b, {}).get(a, 0.0), 3) for a in appliances}
        per[OTHER] = round(max(t - sum(per.values()), 0.0), 3)
        return round(t, 3), per

    out = DisaggregationOut(
        house_id=house_id, period=period, start=start, end=end,
        total_kwh=round(total, 3), breakdown=breakdown,
    )
    buckets = [start + bucket * i for i in range(int((end - start) / bucket))]
    if period == "day":
        out.hourly = [HourlyPoint(hour=b, total_kwh=(s := split(b))[0], by_appliance=s[1]) for b in buckets]
    else:
        out.daily = [DailyPoint(date=b.date(), total_kwh=(s := split(b))[0], by_appliance=s[1]) for b in buckets]
    return out