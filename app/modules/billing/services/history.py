import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.home.api import Home

from ..models import Bill
from .bill import ICT, _add_month, _cycle_start, compute_bill

log = logging.getLogger(__name__)

MAX_CYCLES = 25  # two years of history plus the running cycle


# shortcut: every stored cycle (up to 25) is recomputed on each hourly run, ~0.1 s a home; at
# hundreds of homes recompute only the running and the last cycle, and all of them daily.
async def refresh_bills(session: AsyncSession, home_id: uuid.UUID, now: datetime | None = None):
    """Store the bill of every cycle from the home's first reading to the running one.

    Bills are derived data: recomputed from the readings each time, and the ones whose start no
    longer falls on the home's billing cycle day (the owner changed it) are deleted. A cycle no
    tariff version covers is skipped. The caller commits.
    """
    now = now or datetime.now(UTC)
    home = await session.get(Home, home_id)
    first = await session.scalar(
        text(
            "SELECT r.bucket FROM public.reading_1d r JOIN public.tb_series s USING (series_id) "
            "WHERE s.home_id = :h AND s.kind = 'main' AND s.metric = 'power_w' "
            "ORDER BY r.bucket LIMIT 1"
        ),
        {"h": home_id},
    )
    starts: list = []
    if first is not None and home.tariff_plan_code is not None:
        day = home.billing_cycle_day or 1
        start = _cycle_start(first.astimezone(ICT).date(), day)
        current = _cycle_start(now.astimezone(ICT).date(), day)
        while start <= current:
            starts.append(start)
            start = _add_month(start)  # day <= 28 always exists
        starts = starts[-MAX_CYCLES:]
    for start in starts:
        try:
            await compute_bill(session, home_id, start, now)
        except LookupError as e:  # no tariff version valid on that cycle
            log.warning("home %s: cycle %s not priced: %s", home_id, start, e)
    await session.execute(
        delete(Bill).where(Bill.home_id == home_id, Bill.period_start.not_in(starts))
    )


async def bill_history(session: AsyncSession, home_id: uuid.UUID, now: datetime | None = None):
    """The home's stored bills of ended cycles, oldest first."""
    today = (now or datetime.now(UTC)).astimezone(ICT).date()
    return list(
        await session.scalars(
            select(Bill)
            .where(Bill.home_id == home_id, Bill.period_end < today)
            .order_by(Bill.period_start)
        )
    )
