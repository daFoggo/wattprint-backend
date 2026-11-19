import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.modules.billing.api import MODEL_VERSION, forecast_bill, refresh_bills
from app.modules.copilot.api import measure_plans, prune_scope_tokens, prune_speech
from app.modules.home.api import Home

from ..models import ForecastSnapshot
from .cohort import refresh_cohorts
from .detectors import detect
from .mail import mail_alerts, mail_weekly

log = logging.getLogger("insight.jobs")


async def each_home(work: Callable[[AsyncSession, uuid.UUID], Awaitable[None]]) -> None:
    """Run `work` per home in its own transaction: one home failing does not stop the others."""
    async with SessionLocal() as s:
        homes = list(await s.scalars(select(Home.id).order_by(Home.id)))
    for home_id in homes:
        try:
            async with SessionLocal() as s, s.begin():
                await work(s, home_id)
        except Exception:
            log.exception("home %s failed", home_id)


async def bills(now: datetime) -> None:
    await each_home(lambda s, h: refresh_bills(s, h, now))


async def _snapshot(session: AsyncSession, home_id: uuid.UUID, now: datetime) -> None:
    try:
        f = await forecast_bill(session, home_id, now)
    except LookupError:  # no tariff plan: nothing to price
        return
    if f is None:
        return
    await session.execute(
        insert(ForecastSnapshot)
        .values(
            home_id=home_id,
            generated_at=now,
            horizon_date=f.period_end,
            kwh=f.kwh,
            amount=f.amount,
            tier_cross_date=f.next.on if f.next else None,
            model_version=MODEL_VERSION,
        )
        .on_conflict_do_nothing()
    )


async def forecasts(now: datetime) -> None:
    """One forecast of the running cycle per home per run (daily), kept to track its accuracy."""
    await each_home(lambda s, h: _snapshot(s, h, now))


async def cohorts(now: datetime) -> None:
    async with SessionLocal() as s, s.begin():
        await refresh_cohorts(s, now)


async def alerts(now: datetime) -> None:
    await each_home(lambda s, h: detect(s, h, now))


async def mail(now: datetime) -> None:
    await mail_alerts(now)
    await mail_weekly(now)


async def upkeep(now: datetime) -> None:
    """Expired copilot scope tokens out; plans tried for 14 days measured."""
    async with SessionLocal() as s, s.begin():
        await prune_scope_tokens(s)
        await prune_speech(s)
        await measure_plans(s, now)
