import uuid
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# REFIT recorded in England (2013–2015): its households kept these days off.
ENGLAND_BANK_HOLIDAYS = frozenset(
    date.fromisoformat(d)
    for d in (
        "2012-01-02 2012-04-06 2012-04-09 2012-05-07 2012-06-04 2012-06-05 2012-08-27 "
        "2012-12-25 2012-12-26 2013-01-01 2013-03-29 2013-04-01 2013-05-06 2013-05-27 "
        "2013-08-26 2013-12-25 2013-12-26 2014-01-01 2014-04-18 2014-04-21 2014-05-05 "
        "2014-05-26 2014-08-25 2014-12-25 2014-12-26 2015-01-01 2015-04-03 2015-04-06 "
        "2015-05-04 2015-05-25 2015-08-31 2015-12-25 2015-12-28 2016-01-01 2016-03-25 "
        "2016-03-28 2016-05-02 2016-05-30 2016-08-29 2016-12-26 2016-12-27"
    ).split()
)


def source_date(local_day: date, shift_days: int) -> date:
    """The recording's own date behind a demo home's local day (scripts/refit.py shifts it)."""
    return local_day - timedelta(days=shift_days)


def is_holiday(d: date) -> bool:
    return d in ENGLAND_BANK_HOLIDAYS or (d.month, d.day) >= (12, 24) or (d.month, d.day) == (1, 1)


def meter_serial(source: str) -> str:
    """The demo meter of an etl.tb_watermark source; mirrors scripts/refit.py meter()/source()
    (tests/test_expect_features.py checks they agree)."""
    base, _, variant = source.partition("#")
    house = base.removeprefix("refit/CLEAN_House").removesuffix(".csv")
    return f"REFIT-H{house}" + (f"-{variant.removeprefix(f'{house}-')}" if variant else "")


async def shift_days(s: AsyncSession, home_id: uuid.UUID) -> int | None:
    """A demo home's REFIT shift in days; None for a real home (its calendar is its own)."""
    serials = set(
        await s.scalars(
            text("SELECT serial FROM public.tb_meter WHERE home_id = :h"), {"h": home_id}
        )
    )
    for source, days in await s.execute(
        text("SELECT source, shift_days FROM etl.tb_watermark WHERE segment = 'demo'")
    ):
        if meter_serial(source) in serials:
            return int(days)
    return None
