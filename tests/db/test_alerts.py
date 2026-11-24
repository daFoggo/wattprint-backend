from datetime import date, timedelta

from sqlalchemy import select, text

from app.models import Alert
from app.modules.insight.services.detectors import detect
from tests.db.test_billing import (
    backfill,
    bdb,
    bsession,
    home,
    load,
    local_midnight,
)

__all__ = ["bdb", "bsession"]  # module fixtures reused from the billing tests

NOW = local_midnight(date(2026, 11, 10)) + timedelta(hours=12)
MIN = timedelta(minutes=1)


async def analyzed(c, h, until):
    """NILM's last good run: the device detectors read up to its window_end."""
    await c.execute(
        text(
            "INSERT INTO public.tb_inference_run (home_id, model_name, model_version, "
            "window_start, window_end, status) VALUES (:h, 'test', '1', :lo, :hi, 'ok')"
        ),
        {"h": h["id"], "lo": until - timedelta(days=1), "hi": until},
    )


async def alerts(s, h):
    s.expire_all()
    return {a.dedup_key: a for a in await s.scalars(select(Alert).where(Alert.home_id == h["id"]))}


async def test_standby_high_compares_the_last_three_nights(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        for n in range(1, 32):  # nights 00:00-05:00 local of the 31 days before NOW
            night = local_midnight(date(2026, 11, 10) - timedelta(days=n - 1))
            await load(c, h["main"], night, 300, 300 if n <= 3 else 100)
        await backfill(c, NOW - timedelta(days=32), NOW)
        await detect(bsession, h["id"], NOW)
        await bsession.commit()
        a = (await alerts(bsession, h))["standby_high"]
        assert a.payload == {"usual_w": 100, "recent_w": 300, "nights": 3}


async def test_unexplained_load_raises_then_resolves_when_it_stops(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        did = await c.scalar(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'other', 'Other', 'nilm') RETURNING id"
            ),
            {"h": h["id"]},
        )
        sid = await c.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
                "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"
            ),
            {"h": h["id"], "d": did},
        )
        h["sids"].append(sid)
        start = NOW - timedelta(days=8)
        await load(c, sid, start, 8 * 1440 - 40, 200, "device_estimate")
        await load(c, sid, NOW - 40 * MIN, 40, 1000, "device_estimate")  # 40 min over 200 + 300
        await analyzed(c, h, NOW)
        await backfill(c, start - timedelta(days=1), NOW)
        await detect(bsession, h["id"], NOW)
        await bsession.commit()
        a = (await alerts(bsession, h))["unexplained_load"]
        assert (a.status, a.payload) == ("open", {"watts": 1000, "usual_w": 200, "minutes": 40})

        await load(c, sid, NOW, 5, 150, "device_estimate")
        await analyzed(c, h, NOW + 5 * MIN)
        await backfill(c, NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        await detect(bsession, h["id"], NOW + 5 * MIN)
        await bsession.commit()
        a = (await alerts(bsession, h))["unexplained_load"]
        assert (a.status, a.resolved_at) == ("resolved", NOW + 5 * MIN)


async def test_tier_near_once_the_cycle_is_in_a_higher_tier(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        await load(c, h["main"], local_midnight(date(2026, 11, 1)), 9000)  # 150 kWh
        await backfill(c, local_midnight(date(2026, 10, 30)), NOW)
        await detect(bsession, h["id"], NOW)
        await bsession.commit()
        (a,) = [a for k, a in (await alerts(bsession, h)).items() if k.startswith("tier_near")]
        assert a.dedup_key == f"tier_near:2026-11-01:{a.payload['tier_no']:g}"
        assert a.payload["tier_no"] >= 2 and a.payload["days"] == 0
        assert a.payload["from_kwh"] <= 150
