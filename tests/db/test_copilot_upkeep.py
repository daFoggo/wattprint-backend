from sqlalchemy import text

from app.modules.copilot.services import prune_scope_tokens
from tests.db.test_billing import bdb, bsession, home

__all__ = ["bdb", "bsession"]  # module fixtures reused from the billing tests


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
