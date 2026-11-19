import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.home.api import Home

from ..models import MIN_COHORT_HOMES, CohortStat

ICT = timezone(timedelta(hours=7))
DAYS = 30
MIN_COVERAGE = 0.9  # a home counts when its meter reported 90 % of the window
ALL = "all"


@dataclass
class CohortView:
    cohort_key: str
    period: date  # the window's last day
    days: int
    homes: int
    p10: Decimal  # kWh over the window
    p33: Decimal
    p66: Decimal
    p90: Decimal
    kwh: Decimal | None  # this home over the same window; None when it reported under 90 %


def _window(period: date) -> tuple[datetime, datetime]:
    first = period - timedelta(days=DAYS - 1)
    lo = datetime(first.year, first.month, first.day, tzinfo=ICT).astimezone(UTC)
    return lo, lo + timedelta(days=DAYS)


async def _avg_w(
    session: AsyncSession, period: date, home_id: uuid.UUID | None = None
) -> dict[uuid.UUID, tuple[str | None, float]]:
    """(home type, average power) of each home's main meter over the window, over the minutes it
    reported."""
    lo, hi = _window(period)
    rows = await session.execute(
        text(
            "SELECT s.home_id, h.home_type, sum(r.energy_wh) AS wh, sum(r.covered_minutes) AS cov "
            "FROM public.reading_1d r JOIN public.tb_series s USING (series_id) "
            "JOIN public.tb_home h ON h.id = s.home_id "
            "WHERE s.kind = 'main' AND s.metric = 'power_w' AND r.bucket >= :lo AND r.bucket < :hi "
            "AND (CAST(:h AS uuid) IS NULL OR s.home_id = :h) "
            "GROUP BY s.home_id, h.home_type, s.series_id"
        ),
        {"lo": lo, "hi": hi, "h": home_id},
    )
    need = MIN_COVERAGE * DAYS * 24 * 60
    total: dict[uuid.UUID, tuple[str | None, float]] = {}
    short: set[uuid.UUID] = set()
    for r in rows:  # a home with several mains: sum their averages, all must be covered
        if not r.cov or r.cov < need:
            short.add(r.home_id)
        else:
            w = total.get(r.home_id, (None, 0.0))[1] + float(r.wh) * 60 / float(r.cov)
            total[r.home_id] = (r.home_type, w)
    return {h: v for h, v in total.items() if h not in short}


async def refresh_cohorts(session: AsyncSession, now: datetime) -> None:
    """Percentiles of the window ending yesterday, per home type and over all homes (≥ 10 homes)."""
    period = now.astimezone(ICT).date() - timedelta(days=1)
    avg = await _avg_w(session, period)
    if not avg:
        return
    groups: dict[str, list[float]] = defaultdict(list)
    for home_type, w in avg.values():
        groups[ALL].append(w)
        if home_type:
            groups[home_type].append(w)
    for key, ws in groups.items():
        if len(ws) < MIN_COHORT_HOMES:
            continue
        q = statistics.quantiles(ws, n=100, method="inclusive")
        p = {f"p{k}_w": round(Decimal(q[k - 1]), 2) for k in (10, 33, 66, 90)}
        await session.execute(
            insert(CohortStat)
            .values(cohort_key=key, period=period, n_homes=len(ws), **p)
            .on_conflict_do_update(
                index_elements=["cohort_key", "period"], set_={"n_homes": len(ws), **p}
            )
        )


def _kwh(w: Decimal | float) -> Decimal:
    return round(Decimal(w) * 24 * DAYS / 1000, 1)


async def cohort_for(session: AsyncSession, home_id: uuid.UUID) -> CohortView | None:
    """Latest stats of the home's type, else of all homes; None while no cohort is big enough."""
    home_type = await session.scalar(select(Home.home_type).where(Home.id == home_id))
    keys = [k for k in (home_type, ALL) if k]
    stats = (
        await session.scalars(
            select(CohortStat)
            .where(CohortStat.cohort_key.in_(keys))
            .order_by(CohortStat.period.desc())
        )
    ).all()
    if not stats:
        return None
    latest = stats[0].period
    c = min((s for s in stats if s.period == latest), key=lambda s: keys.index(s.cohort_key))
    own = (await _avg_w(session, latest, home_id)).get(home_id, (None, None))[1]
    return CohortView(
        cohort_key=c.cohort_key,
        period=c.period,
        days=DAYS,
        homes=c.n_homes,
        p10=_kwh(c.p10_w),
        p33=_kwh(c.p33_w),
        p66=_kwh(c.p66_w),
        p90=_kwh(c.p90_w),
        kwh=_kwh(own) if own is not None else None,
    )
