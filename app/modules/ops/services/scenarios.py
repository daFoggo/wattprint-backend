import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DemoScenario


async def scenarios_between(
    s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime
) -> list[DemoScenario]:
    """Scenarios of the home whose window overlaps [lo, hi] (an open end runs on)."""
    rows = await s.scalars(
        select(DemoScenario)
        .where(
            DemoScenario.home_id == home_id,
            DemoScenario.starts_at <= hi,
            or_(DemoScenario.ends_at.is_(None), DemoScenario.ends_at > lo),
        )
        .order_by(DemoScenario.starts_at)
    )
    return list(rows)
