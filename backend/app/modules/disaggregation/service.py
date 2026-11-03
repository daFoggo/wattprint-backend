from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import BreakdownItem, DailyPoint, DisaggregationOut, HourlyPoint, LatestOut, LatestPoint

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
_SQL_ACCURACY = text("""
    SELECT p.appliance,
           SUM(p.watts) * :k AS pred_kwh,
           SUM(t.watts) * :k AS true_kwh,
           SUM(ABS(p.watts - t.watts)) * :k AS abs_err_kwh
    FROM appliance_power p
    JOIN appliance_truth t
      ON t.house_id = p.house_id AND t.appliance = p.appliance AND t.ts = p.ts
    WHERE p.house_id = :h AND p.ts >= :start AND p.ts < :end
    GROUP BY p.appliance
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
    truth = {r.appliance: r for r in await db.execute(_SQL_ACCURACY, p)}
    agg_bucket = {r.b: r.kwh for r in await db.execute(_SQL_AGG_BUCKET, {**p, "bucket": bucket})}
    app_bucket: dict[datetime, dict[str, float]] = defaultdict(dict)
    for r in await db.execute(_SQL_APP_BUCKET, {**p, "bucket": bucket}):
        app_bucket[r.b][r.appliance] = r.kwh

    total = sum(agg_bucket.values())
    appliances = sorted(set(KNOWN_APPLIANCES) | set(by_app), key=lambda a: by_app.get(a, 0.0), reverse=True)

    def pct(v: float) -> float:
        return round(v / total * 100, 1) if total > 0 else 0.0

    other = max(total - sum(by_app.values()), 0.0)
    breakdown = []
    for a in appliances:
        kwh_a = by_app.get(a, 0.0)
        item = BreakdownItem(appliance=a, kwh=round(kwh_a, 3), percent=pct(kwh_a))
        tr = truth.get(a)
        if tr is not None and tr.true_kwh > 0:
            item.true_kwh = round(tr.true_kwh, 3)
            item.accuracy_pct = round(max(0.0, 1 - tr.abs_err_kwh / (2 * tr.true_kwh)) * 100, 1)
            item.energy_error_pct = round((tr.pred_kwh - tr.true_kwh) / tr.true_kwh * 100, 1)
        breakdown.append(item)
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
    out.explained_pct = round((total - other) / total * 100, 1) if total > 0 else None
    t_sum = sum(r.true_kwh for r in truth.values())
    e_sum = sum(r.abs_err_kwh for r in truth.values())
    out.accuracy_pct = round(max(0.0, 1 - e_sum / (2 * t_sum)) * 100, 1) if t_sum > 0 else None
    buckets = [start + bucket * i for i in range(int((end - start) / bucket))]
    if period == "day":
        out.hourly = [HourlyPoint(hour=b, total_kwh=(s := split(b))[0], by_appliance=s[1]) for b in buckets]
    else:
        out.daily = [DailyPoint(date=b.date(), total_kwh=(s := split(b))[0], by_appliance=s[1]) for b in buckets]
    return out

async def get_latest(db: AsyncSession, house_id: int, minutes: int) -> LatestOut:
    rows = (await db.execute(
        text("SELECT ts, watts FROM aggregate_power WHERE house_id = :h ORDER BY ts DESC LIMIT :n"),
        {"h": house_id, "n": minutes},
    )).all()
    if not rows:
        return LatestOut(house_id=house_id, points=[])
    rows.reverse()  # cũ -> mới
    pred: dict[datetime, dict[str, float]] = defaultdict(dict)
    result = await db.execute(
        text("SELECT ts, appliance, watts FROM appliance_power WHERE house_id = :h AND ts >= :t0"),
        {"h": house_id, "t0": rows[0].ts},
    )
    for r in result:
        pred[r.ts][r.appliance] = round(r.watts, 1)
    truth: dict[datetime, dict[str, float]] = defaultdict(dict)
    truth_rows = await db.execute(
        text("SELECT ts, appliance, watts FROM appliance_truth WHERE house_id = :h AND ts >= :t0"),
        {"h": house_id, "t0": rows[0].ts},
    )
    for r in truth_rows:
        truth[r.ts][r.appliance] = round(r.watts, 1)

    points = []
    for r in rows:
        ap = pred.get(r.ts)
        tr = truth.get(r.ts)
        points.append(LatestPoint(
            ts=r.ts, aggregate_w=round(r.watts, 1), appliances_w=ap,
            other_w=round(max(r.watts - sum(ap.values()), 0.0), 1) if ap else None,
            truth_w=tr,
            error_w={a: round(tr[a] - ap[a], 1) for a in ap if a in tr} if ap and tr else None,
        ))
    return LatestOut(house_id=house_id, points=points)