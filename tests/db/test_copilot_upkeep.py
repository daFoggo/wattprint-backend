from datetime import date, timedelta

from sqlalchemy import text

from app.modules.copilot.services import measure_plans, prune_scope_tokens
from tests.db.test_billing import backfill, bdb, bsession, home, load, local_midnight

__all__ = ["bdb", "bsession"]  # module fixtures reused from the billing tests

ACCEPTED = local_midnight(date(2026, 10, 20))


async def test_a_plan_is_measured_after_14_days_once(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        user = await c.scalar(
            text("INSERT INTO public.tb_users (email) VALUES ('mv@test') RETURNING id")
        )
        plan = await c.scalar(
            text(
                "INSERT INTO public.tb_suggestion (home_id, kind, title, body, status) "
                "VALUES (:h, 'plan', 'p', '[]', 'accepted') RETURNING id"
            ),
            {"h": h["id"]},
        )
        await c.execute(
            text(
                "INSERT INTO public.tb_suggestion_feedback (suggestion_id, user_id, action, at) "
                "VALUES (:p, :u, 'accept', :at)"
            ),
            {"p": plan, "u": user, "at": ACCEPTED},
        )
        await load(c, h["main"], ACCEPTED - timedelta(days=14), 14 * 1440, 1000)  # 336 kWh
        await load(c, h["main"], ACCEPTED, 14 * 1440, 750)  # 252 kWh
        await backfill(c, ACCEPTED - timedelta(days=15), ACCEPTED + timedelta(days=15))
        try:
            await measure_plans(bsession, ACCEPTED + timedelta(days=13))  # not due yet
            await bsession.commit()
            count = "SELECT count(*) FROM public.tb_savings_measure WHERE suggestion_id = :p"
            assert await c.scalar(text(count), {"p": plan}) == 0
            for _ in range(2):
                await measure_plans(bsession, ACCEPTED + timedelta(days=15))
                await bsession.commit()
            row = (
                await c.execute(
                    text(
                        "SELECT baseline_kwh, actual_kwh FROM public.tb_savings_measure "
                        "WHERE suggestion_id = :p"
                    ),
                    {"p": plan},
                )
            ).one()
            assert (float(row.baseline_kwh), float(row.actual_kwh)) == (336.0, 252.0)
        finally:
            await c.execute(text("DELETE FROM public.tb_users WHERE id = :u"), {"u": user})


async def test_expired_scope_tokens_are_pruned(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        await c.execute(
            text(
                "INSERT INTO public.tb_scope_token (home_id, expires_at) VALUES "
                "(:h, now() - interval '1 minute'), (:h, now() + interval '5 minutes')"
            ),
            {"h": h["id"]},
        )
        await prune_scope_tokens(bsession)
        await bsession.commit()
        left = "SELECT count(*) FROM public.tb_scope_token WHERE home_id = :h"
        assert await c.scalar(text(left), {"h": h["id"]}) == 1
