from contextlib import AsyncExitStack
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, text

from app.models import CohortStat
from app.modules.insight.services import cohort_for, refresh_cohorts
from tests.db.test_billing import backfill, bdb, bsession, home, load, local_midnight

__all__ = ["bdb", "bsession"]  # module fixtures reused from the billing tests

NOW = local_midnight(date(2026, 11, 10)) + timedelta(hours=9)
FIRST = local_midnight(date(2026, 10, 10))  # the 30 days ending 9/11


async def _homes(stack, c, s, n, home_type, watts=lambda i: 100 * (i + 1), minutes=30 * 1440):
    hs = []
    for i in range(n):
        h = await stack.enter_async_context(home(c, s))
        await c.execute(
            text("UPDATE public.tb_home SET home_type = :t WHERE id = :h"),
            {"t": home_type, "h": h["id"]},
        )
        await load(c, h["main"], FIRST, minutes, watts(i))
        hs.append(h)
    return hs


async def test_cohort_needs_ten_covered_homes_and_prefers_the_home_type(bdb, bsession):
    c, _ = bdb
    async with AsyncExitStack() as stack:
        houses = await _homes(stack, c, bsession, 9, "house")
        # 20 of 30 days: under 90 % covered, never counted
        (short,) = await _homes(stack, c, bsession, 1, "house", minutes=20 * 1440)
        await backfill(c, FIRST - timedelta(days=1), NOW)
        await refresh_cohorts(bsession, NOW)
        await bsession.commit()
        assert not (await bsession.scalars(select(CohortStat))).all()
        assert await cohort_for(bsession, houses[0]["id"]) is None

        houses += await _homes(stack, c, bsession, 1, "house", watts=lambda _: 1000)
        (flat,) = await _homes(stack, c, bsession, 1, "apartment", watts=lambda _: 500)
        await backfill(c, FIRST - timedelta(days=1), NOW)
        await refresh_cohorts(bsession, NOW)
        await bsession.commit()
        rows = {r.cohort_key: r for r in await bsession.scalars(select(CohortStat))}
        assert set(rows) == {"house", "all"}  # one apartment is too few for its own cohort
        assert (rows["house"].n_homes, rows["all"].n_homes) == (10, 11)
        assert rows["house"].period == date(2026, 11, 9)
        # 100..1000 W: the 10th percentile sits 0.9 of the way from 100 to 200
        assert (rows["house"].p10_w, rows["house"].p90_w) == (Decimal("190.00"), Decimal("910.00"))

        mine = await cohort_for(bsession, houses[0]["id"])
        assert (mine.cohort_key, mine.homes, mine.days) == ("house", 10, 30)
        assert mine.p10 == Decimal("136.8")  # 190 W over 30 days
        assert mine.kwh == Decimal("72.0")  # 100 W over 30 days
        assert (await cohort_for(bsession, flat["id"])).cohort_key == "all"
        assert (await cohort_for(bsession, short["id"])).kwh is None
