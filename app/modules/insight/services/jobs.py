import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import outbound
from app.database import SessionLocal
from app.modules.billing.api import forecast_bill, refresh_bills
from app.modules.copilot.api import prune_scope_tokens, prune_speech
from app.modules.expect.api import refresh_home, train_device, train_home
from app.modules.home.api import Home

from ..models import ForecastSnapshot
from .cohort import refresh_cohorts
from .detectors import detect
from .mail import mail_alerts, mail_weekly
from .plans import freeze_plans
from .watches import check_due, prune_watches

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
            model_version=f.model_version,
            kwh_p10=f.kwh_p10,
            kwh_p90=f.kwh_p90,
            drivers=f.drivers,
        )
        .on_conflict_do_nothing()
    )


async def train_devices(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> None:
    """Each device's model in its own savepoint: one that cannot be learnt (a device always at 0 W)
    is logged and leaves the home's model and the other devices alone."""
    devices = await s.scalars(
        text(
            "SELECT d.id FROM public.tb_device d JOIN public.tb_series x ON x.device_id = d.id "
            "AND x.kind = 'device' WHERE d.home_id = :h AND d.device_type_code <> 'other' "
            "AND d.deleted_at IS NULL"
        ),
        {"h": home_id},
    )
    for device_id in devices.all():  # "Other" is what no device explains: no model of its own
        try:
            async with s.begin_nested():
                if v := await train_device(s, home_id, device_id, now):
                    log.info("device %s: expected-usage model %s", device_id, v)
        except Exception:
            log.exception("device %s: model not learnt", device_id)


async def expect_train(now: datetime) -> None:
    """Relearn each home's expected-usage model from its days up to yesterday (daily)."""

    async def work(s: AsyncSession, home_id: uuid.UUID) -> None:
        version = await train_home(s, home_id, now)
        if version:
            log.info("home %s: expected-usage model %s", home_id, version)
        await train_devices(s, home_id, now)

    await each_home(work)


async def expect_refresh(now: datetime) -> None:
    """Expected kWh per hour for each home with a model (hourly)."""

    async def work(s: AsyncSession, home_id: uuid.UUID) -> None:
        # Plans first: after a refit, refresh_home rewrites the past hours with the new model.
        try:
            async with s.begin_nested():
                await freeze_plans(s, home_id, now)
        except Exception:
            log.exception("home %s: savings plans not frozen", home_id)
        await refresh_home(s, home_id, now)

    await each_home(work)


async def forecasts(now: datetime) -> None:
    """One forecast of the running cycle per home per run (daily), kept to track its accuracy."""
    await each_home(lambda s, h: _snapshot(s, h, now))


async def cohorts(now: datetime) -> None:
    async with SessionLocal() as s, s.begin():
        await refresh_cohorts(s, now)


async def alerts(now: datetime) -> None:
    await each_home(lambda s, h: detect(s, h, now))


async def watches(now: datetime) -> None:
    n = await check_due(now)
    if n:
        log.info("%d watches checked", n)


async def mail(now: datetime) -> None:
    await mail_alerts(now)
    await mail_weekly(now)


async def upkeep(now: datetime) -> None:
    """Expired copilot scope tokens, long-ended watches and old speech out."""
    async with SessionLocal() as s, s.begin():
        await prune_scope_tokens(s)
        await prune_watches(s, now)
        await prune_speech(s)
    await outbound.prune()  # the outbound log keeps 90 days
