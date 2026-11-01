import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _user(conn) -> uuid.UUID:
    uid = uuid.uuid4()
    await conn.execute(
        text("INSERT INTO public.users (id, email) VALUES (:i, :e)"),
        {"i": uid, "e": f"{uid}@example.com"},
    )
    return uid


async def _home(conn, **overrides) -> uuid.UUID:
    hid = uuid.uuid4()
    cols = {"id": hid, "name": "Home", **overrides}
    names = ", ".join(cols)
    params = ", ".join(f":{k}" for k in cols)
    await conn.execute(text(f"INSERT INTO core.home ({names}) VALUES ({params})"), cols)
    return hid


async def test_user_can_join_only_one_home(conn):
    uid = await _user(conn)
    h1, h2 = await _home(conn), await _home(conn)
    await conn.execute(
        text("INSERT INTO core.home_member (home_id, user_id, role) VALUES (:h, :u, 'owner')"),
        {"h": h1, "u": uid},
    )
    with pytest.raises(IntegrityError):
        await conn.execute(
            text("INSERT INTO core.home_member (home_id, user_id, role) VALUES (:h, :u, 'member')"),
            {"h": h2, "u": uid},
        )


async def test_home_timezone_check(conn):
    hid = await _home(conn)
    tz = await conn.scalar(text("SELECT timezone FROM core.home WHERE id = :i"), {"i": hid})
    assert tz == "Asia/Ho_Chi_Minh"
    with pytest.raises(IntegrityError):
        await _home(conn, timezone="UTC")


@pytest.mark.parametrize("day", [0, 29])
async def test_billing_cycle_day_range(conn, day):
    with pytest.raises(IntegrityError):
        await _home(conn, billing_cycle_day=day)


async def test_billing_cycle_day_bounds_accepted(conn):
    await _home(conn, billing_cycle_day=1)
    await _home(conn, billing_cycle_day=28)


async def test_invite_stores_hash_only(conn):
    rows = await conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'core' AND table_name = 'home_invite'"
        )
    )
    cols = {r[0] for r in rows}
    assert "code_hash" in cols
    assert not (cols & {"code", "plain_code", "invite_code", "token"})


async def test_meter_serial_unique(conn):
    q = text("INSERT INTO core.meter (serial, status) VALUES ('SN-1', 'new')")
    await conn.execute(q)
    with pytest.raises(IntegrityError):
        await conn.execute(q)


async def test_device_validity_range_check(conn):
    hid = await _home(conn)
    q = text(
        "INSERT INTO core.device (home_id, device_type_code, name, origin, active_from, active_to)"
        " VALUES (:h, 'fridge', 'Fridge', 'manual', :f, :t)"
    )
    f = datetime(2026, 1, 2, tzinfo=UTC)
    await conn.execute(q, {"h": hid, "f": f, "t": datetime(2026, 1, 3, tzinfo=UTC)})
    for to in (f, datetime(2026, 1, 1, tzinfo=UTC)):
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await conn.execute(q, {"h": hid, "f": f, "t": to})


async def test_device_type_fk(conn):
    hid = await _home(conn)
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO core.device (home_id, device_type_code, name, origin)"
                " VALUES (:h, 'nope', 'X', 'manual')"
            ),
            {"h": hid},
        )


async def test_metric_seed_has_power_w(conn):
    rows = await conn.execute(text("SELECT event_type, unit, aggregation FROM catalog.metric"))
    metrics = {r[0]: (r[1], r[2]) for r in rows}
    assert metrics["power_w"] == ("W", "mean")
    assert metrics["energy_wh"] == ("Wh", "energy")
    assert set(metrics) >= {"reactive_power_var", "voltage_v", "current_a"}


async def test_device_type_seed(conn):
    codes = {r[0] for r in await conn.execute(text("SELECT code FROM catalog.device_type"))}
    assert codes >= {
        "ac", "fridge", "freezer", "fridge_freezer", "washing_machine", "washer_dryer",
        "tumble_dryer", "dishwasher", "television", "computer", "microwave", "kettle",
        "toaster", "hifi", "electric_heater", "router", "water_heater", "electric_car",
        "lights", "oven", "always_on", "other",
    }
    missing = await conn.scalar(
        text("SELECT count(*) FROM catalog.device_type WHERE label_vi = '' OR label_en = ''")
    )
    assert missing == 0
