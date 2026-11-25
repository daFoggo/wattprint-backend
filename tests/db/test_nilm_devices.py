from sqlalchemy import text

from app.modules.nilm.services.devices import ensure_devices
from tests.db.test_billing import bdb, bsession, home

__all__ = ["bdb", "bsession"]  # module fixtures reused from the billing tests


async def test_a_second_fridge_stays_off_the_timeline_like_the_fridge_freezer(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        await ensure_devices(bsession, h["id"], ["Fridge", "Kimchi", "RiceCooker"])
        rows = (
            await bsession.execute(
                text(
                    "SELECT device_type_code, show_on_timeline FROM public.tb_device "
                    "WHERE home_id = :h"
                ),
                {"h": h["id"]},
            )
        ).all()
    assert {r[0]: r[1] for r in rows} == {
        "fridge_freezer": False,
        "fridge": False,
        "rice_cooker": True,
        "other": False,  # the remainder is always there
    }
