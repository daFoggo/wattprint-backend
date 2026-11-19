import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.api import current_bill, forecast_bill
from app.modules.energy.api import analyzed_until

from ..models import Alert
from .cycles import refresh_cycles

ICT = timezone(timedelta(hours=7))
BASE_DAYS = 28  # the usual: the 28 days (or nights) before the recent ones
RECENT_DAYS = 3
CYCLIC = ("fridge", "fridge_freezer", "freezer")  # run length is the appliance's, not the user's
LONGER = 1.5
MIN_RUNS = 3
STANDBY_RATIO, STANDBY_PLUS_W = 1.3, 50.0
NIGHT_END_H = 5  # standby is read 00:00-05:00, when little is switched on by hand
UNEXPLAINED_PLUS_W = 300.0
UNEXPLAINED_MIN = 30
TIER_DAYS = 3


@dataclass
class Finding:
    kind: str
    dedup_key: str
    severity: str
    payload: dict[str, float]
    device_id: uuid.UUID | None = None


# Each detector returns what holds now, or None when the data cannot tell (then its open alerts
# stay as they are instead of being resolved for lack of data).


async def _longer_than_usual(s: AsyncSession, home_id: uuid.UUID, until: datetime):
    split = until - timedelta(days=RECENT_DAYS)
    rows = await s.execute(
        text(
            "SELECT c.device_id, c.start_ts >= :split AS recent, "
            "extract(epoch FROM c.end_ts - c.start_ts) / 60 AS minutes "
            "FROM public.tb_device_cycle c JOIN public.tb_device d ON d.id = c.device_id "
            "WHERE c.home_id = :h AND d.device_type_code = ANY(:types) AND c.start_ts >= :lo"
        ),
        {
            "h": home_id,
            "types": list(CYCLIC),
            "split": split,
            "lo": split - timedelta(days=BASE_DAYS),
        },
    )
    runs: dict[uuid.UUID, tuple[list[float], list[float]]] = {}
    for r in rows:
        runs.setdefault(r.device_id, ([], []))[r.recent].append(float(r.minutes))
    out = []
    for device_id, (usual, recent) in runs.items():
        if len(usual) < MIN_RUNS or len(recent) < MIN_RUNS:
            continue
        u, n = statistics.median(usual), statistics.median(recent)
        if n > LONGER * u:
            out.append(
                Finding(
                    "longer_than_usual",
                    f"longer_than_usual:{device_id}",
                    "warning",
                    {"usual_min": round(u), "recent_min": round(n), "days": RECENT_DAYS},
                    device_id,
                )
            )
    return out


async def _standby_high(s: AsyncSession, home_id: uuid.UUID, now: datetime):
    last_night = (now.astimezone(ICT) - timedelta(hours=NIGHT_END_H)).date()
    first_recent = last_night - timedelta(days=RECENT_DAYS - 1)

    def midnight(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=ICT).astimezone(UTC)

    r = (
        await s.execute(
            text(
                "WITH m AS (SELECT r.bucket >= :split AS recent, sum(r.avg_w) AS w "
                "FROM public.reading_1m r JOIN public.tb_series s USING (series_id) "
                "WHERE s.home_id = :h AND s.kind = 'main' AND s.metric = 'power_w' "
                "AND r.bucket >= :lo AND r.bucket < :hi "
                "AND extract(hour FROM r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh') < :end_h "
                "GROUP BY r.bucket) "
                "SELECT percentile_cont(0.05) WITHIN GROUP (ORDER BY w) FILTER (WHERE recent) AS n,"
                " count(*) FILTER (WHERE recent) AS n_min, "
                "percentile_cont(0.05) WITHIN GROUP (ORDER BY w) FILTER (WHERE NOT recent) AS u, "
                "count(*) FILTER (WHERE NOT recent) AS u_min FROM m"
            ),
            {
                "h": home_id,
                "split": midnight(first_recent),
                "lo": midnight(first_recent - timedelta(days=BASE_DAYS)),
                "hi": midnight(last_night + timedelta(days=1)),
                "end_h": NIGHT_END_H,
            },
        )
    ).one()
    night = NIGHT_END_H * 60
    if (
        r.n_min < 0.8 * RECENT_DAYS * night or r.u_min < 0.8 * 7 * night
    ):  # a week of nights at least
        return None
    if r.n > STANDBY_RATIO * r.u and r.n - r.u > STANDBY_PLUS_W:
        return [
            Finding(
                "standby_high",
                "standby_high",
                "info",
                {"usual_w": round(r.u), "recent_w": round(r.n), "nights": RECENT_DAYS},
            )
        ]
    return []


async def _unexplained_load(s: AsyncSession, home_id: uuid.UUID, until: datetime):
    other = await s.scalar(
        text(
            "SELECT s.series_id FROM public.tb_series s "
            "JOIN public.tb_device d ON d.id = s.device_id "
            "WHERE s.home_id = :h AND s.kind = 'device' AND d.device_type_code = 'other' LIMIT 1"
        ),
        {"h": home_id},
    )
    if other is None:
        return None
    recent_lo = until - timedelta(hours=6)
    base = (
        await s.execute(
            text(
                "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY avg_w) AS p95, count(*) AS n "
                "FROM public.device_estimate_1m WHERE series_id = :s AND bucket >= :lo "
                "AND bucket < :hi"
            ),
            {"s": other, "lo": recent_lo - timedelta(days=BASE_DAYS), "hi": recent_lo},
        )
    ).one()
    if base.n < 0.8 * 7 * 1440:
        return None
    bar = float(base.p95) + UNEXPLAINED_PLUS_W
    minutes = (
        await s.execute(
            text(
                "SELECT bucket, avg_w FROM public.device_estimate_1m WHERE series_id = :s "
                "AND bucket >= :lo AND bucket < :hi ORDER BY bucket DESC"
            ),
            {"s": other, "lo": recent_lo, "hi": until},
        )
    ).all()
    streak, watts, expect = 0, 0.0, None
    for m in minutes:  # back from the newest minute, while it stays over the bar without a gap
        if float(m.avg_w) <= bar or (expect is not None and m.bucket != expect):
            break
        streak, watts, expect = streak + 1, watts + float(m.avg_w), m.bucket - timedelta(minutes=1)
    if streak < UNEXPLAINED_MIN:
        return []
    return [
        Finding(
            "unexplained_load",
            "unexplained_load",
            "warning",
            {"watts": round(watts / streak), "usual_w": round(base.p95), "minutes": streak},
        )
    ]


async def _tier_near(s: AsyncSession, home_id: uuid.UUID, now: datetime):
    try:
        bill = await current_bill(s, home_id, now)
        f = await forecast_bill(s, home_id, now)
    except LookupError:  # no tariff: nothing to warn about
        return []
    today = now.astimezone(ICT).date()
    near = {}
    if bill.tier_no >= 2:  # already in a higher tier this cycle
        t = next(t for t in bill.tiers if t.tier_no == bill.tier_no)
        near[t.tier_no] = (t.from_kwh, t.price_per_kwh, 0)
    if f and f.next and (f.next.on - today).days <= TIER_DAYS:
        n = f.next
        near[n.tier_no] = (n.from_kwh, n.price_per_kwh, max(0, (n.on - today).days))
    return [
        Finding(
            "tier_near",
            f"tier_near:{bill.period_start}:{tier}",
            "info",
            {"tier_no": tier, "from_kwh": float(k), "price_per_kwh": float(p), "days": d},
        )
        for tier, (k, p, d) in near.items()
    ]


async def _upsert(s: AsyncSession, home_id: uuid.UUID, f: Finding, now: datetime) -> None:
    stmt = insert(Alert).values(
        home_id=home_id,
        device_id=f.device_id,
        kind=f.kind,
        severity=f.severity,
        ts=now,
        payload=f.payload,
        dedup_key=f.dedup_key,
    )
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=["home_id", "dedup_key"],
            index_where=Alert.status != "resolved",
            set_={"payload": stmt.excluded.payload, "severity": stmt.excluded.severity},
        )
    )


async def detect(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> None:
    """Raise what holds now, refresh the figures of what is already open, resolve what no longer
    holds. Device checks are as of what NILM has analysed, not the wall clock."""
    until = await analyzed_until(s, home_id)
    if until is not None:
        await refresh_cycles(s, home_id, until)
    checks = {
        "longer_than_usual": lambda: _longer_than_usual(s, home_id, until) if until else None,
        "standby_high": lambda: _standby_high(s, home_id, now),
        "unexplained_load": lambda: _unexplained_load(s, home_id, until) if until else None,
        "tier_near": lambda: _tier_near(s, home_id, now),
    }
    for kind, check in checks.items():
        pending = check()
        found = await pending if pending is not None else None
        if found is None:
            continue
        for f in found:
            await _upsert(s, home_id, f, now)
        await s.execute(
            update(Alert)
            .where(
                Alert.home_id == home_id,
                Alert.kind == kind,
                Alert.status != "resolved",
                Alert.dedup_key.not_in([f.dedup_key for f in found]),
            )
            .values(status="resolved", resolved_at=now)
        )
