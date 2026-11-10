import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _user(conn) -> int:
    return await conn.scalar(
        text("INSERT INTO public.tb_users (email) VALUES (:e) RETURNING id"),
        {"e": f"{uuid.uuid4()}@example.com"},
    )


async def _home(conn, **overrides) -> int:
    cols = {"name": "Home", **overrides}
    names = ", ".join(cols)
    params = ", ".join(f":{k}" for k in cols)
    return await conn.scalar(
        text(f"INSERT INTO public.tb_home ({names}) VALUES ({params}) RETURNING id"), cols
    )


async def test_user_can_join_only_one_home(conn):
    uid = await _user(conn)
    h1, h2 = await _home(conn), await _home(conn)
    await conn.execute(
        text("INSERT INTO public.tb_home_member (home_id, user_id, role) VALUES (:h, :u, 'owner')"),
        {"h": h1, "u": uid},
    )
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO public.tb_home_member (home_id, user_id, role) VALUES (:h, :u, 'member')"
            ),
            {"h": h2, "u": uid},
        )


async def test_home_timezone_check(conn):
    hid = await _home(conn)
    tz = await conn.scalar(text("SELECT timezone FROM public.tb_home WHERE id = :i"), {"i": hid})
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
            "WHERE table_schema = 'public' AND table_name = 'tb_home_invite'"
        )
    )
    cols = {r[0] for r in rows}
    assert "code_hash" in cols
    assert not (cols & {"code", "plain_code", "invite_code", "token"})


async def test_meter_serial_unique(conn):
    q = text("INSERT INTO public.tb_meter (serial, status) VALUES ('SN-1', 'new')")
    await conn.execute(q)
    with pytest.raises(IntegrityError):
        await conn.execute(q)


async def test_device_validity_range_check(conn):
    hid = await _home(conn)
    q = text(
        "INSERT INTO public.tb_device "
        "(home_id, device_type_code, name, origin, active_from, active_to)"
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
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin)"
                " VALUES (:h, 'nope', 'X', 'manual')"
            ),
            {"h": hid},
        )


async def test_metric_seed_has_power_w(conn):
    rows = await conn.execute(text("SELECT event_type, unit, aggregation FROM public.cat_metric"))
    metrics = {r[0]: (r[1], r[2]) for r in rows}
    assert metrics["power_w"] == ("W", "mean")
    assert metrics["energy_wh"] == ("Wh", "energy")
    assert set(metrics) >= {"reactive_power_var", "voltage_v", "current_a"}


async def test_device_type_seed(conn):
    codes = {r[0] for r in await conn.execute(text("SELECT code FROM public.cat_device_type"))}
    assert codes >= {
        "ac",
        "fridge",
        "freezer",
        "fridge_freezer",
        "washing_machine",
        "washer_dryer",
        "tumble_dryer",
        "dishwasher",
        "television",
        "computer",
        "microwave",
        "kettle",
        "toaster",
        "hifi",
        "electric_heater",
        "router",
        "water_heater",
        "electric_car",
        "lights",
        "oven",
        "always_on",
        "other",
    }
    missing = await conn.scalar(
        text("SELECT count(*) FROM public.cat_device_type WHERE label_vi = '' OR label_en = ''")
    )
    assert missing == 0


# --- ORM round trip and metadata ---


def test_metadata_sorted_tables_resolves():
    from app.database import Base

    names = {t.fullname for t in Base.metadata.sorted_tables}
    assert {
        "users",
        "public.tb_home",
        "public.tb_home_member",
        "public.tb_device",
        "public.cat_metric",
    } <= names


async def test_orm_round_trip(session):
    from sqlalchemy import select

    from app.models import (
        Device,
        DeviceAlertRule,
        DeviceType,
        Home,
        HomeInvite,
        HomeMember,
        Meter,
        User,
    )

    user = User(email=f"{uuid.uuid4()}@example.com")
    home = Home(name="My home", home_type="apartment")
    session.add_all([user, home])
    await session.flush()
    expires = datetime(2030, 1, 1, tzinfo=UTC)
    session.add_all(
        [
            HomeMember(home_id=home.id, user_id=user.id, role="owner"),
            HomeInvite(home_id=home.id, code_hash="h" * 64, expires_at=expires),
            Meter(serial="SN-ORM", home_id=home.id, claim_code_hash="c" * 64),
        ]
    )
    session.add(DeviceType(code="orm_test_type", label_vi="Thu", label_en="Test"))
    await session.flush()
    device = Device(
        home_id=home.id, device_type_code="orm_test_type", name="Gadget", origin="manual"
    )
    session.add(device)
    await session.flush()
    session.add(DeviceAlertRule(device_id=device.id, kind="on"))
    await session.flush()
    home_id = home.id
    session.expire_all()

    member = (await session.execute(select(HomeMember).join(User))).scalar_one()
    assert member.home_id == home_id and member.role == "owner"
    invite = (await session.execute(select(HomeInvite))).scalar_one()
    assert invite.role == "member" and invite.used_by is None
    assert (await session.execute(select(Meter))).scalar_one().status == "new"
    got = (await session.execute(select(Device))).scalar_one()
    assert got.show_on_timeline is True and got.active_from is not None
    rule = (await session.execute(select(DeviceAlertRule))).scalar_one()
    assert rule.params == {} and rule.enabled is True


# --- CHECK vocabularies ---


async def _device(conn, home_id, **overrides) -> int:
    cols = {
        "home_id": home_id,
        "device_type_code": "fridge",
        "name": "D",
        "origin": "manual",
        **overrides,
    }
    names = ", ".join(cols)
    params = ", ".join(f":{k}" for k in cols)
    return await conn.scalar(
        text(f"INSERT INTO public.tb_device ({names}) VALUES ({params}) RETURNING id"), cols
    )


async def _rejects(conn, sql, params=None):
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(text(sql), params or {})


async def test_home_type_check(conn):
    await _home(conn, home_type="house")
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await _home(conn, home_type="castle")


async def test_member_and_invite_role_check(conn):
    uid, hid = await _user(conn), await _home(conn)
    await conn.execute(
        text("INSERT INTO public.tb_home_member (home_id, user_id, role) VALUES (:h, :u, 'member')"),
        {"h": hid, "u": uid},
    )
    uid2 = await _user(conn)
    await _rejects(
        conn,
        "INSERT INTO public.tb_home_member (home_id, user_id, role) VALUES (:h, :u, 'admin')",
        {"h": hid, "u": uid2},
    )
    ins = (
        "INSERT INTO public.tb_home_invite (home_id, code_hash, role, expires_at)"
        " VALUES (:h, :c, :r, now())"
    )
    await conn.execute(text(ins), {"h": hid, "c": "a", "r": "owner"})
    await _rejects(conn, ins, {"h": hid, "c": "b", "r": "admin"})


async def test_invite_code_hash_unique(conn):
    hid = await _home(conn)
    ins = "INSERT INTO public.tb_home_invite (home_id, code_hash, expires_at) VALUES (:h, 'x', now())"
    await conn.execute(text(ins), {"h": hid})
    await _rejects(conn, ins, {"h": hid})


async def test_device_origin_check(conn):
    hid = await _home(conn)
    await _device(conn, hid, origin="nilm")
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await _device(conn, hid, origin="magic")


async def test_alert_rule_kind_check(conn):
    did = await _device(conn, await _home(conn))
    ins = "INSERT INTO public.tb_device_alert_rule (device_id, kind) VALUES (:d, :k)"
    await conn.execute(text(ins), {"d": did, "k": "custom"})
    await _rejects(conn, ins, {"d": did, "k": "sms"})


async def test_meter_status_check(conn):
    ins = "INSERT INTO public.tb_meter (serial, status) VALUES (:s, :t)"
    await conn.execute(text(ins), {"s": "S1", "t": "active"})
    await _rejects(conn, ins, {"s": "S2", "t": "broken"})


async def test_metric_aggregation_check(conn):
    ins = "INSERT INTO public.cat_metric (event_type, unit, aggregation) VALUES (:e, 'W', :a)"
    await conn.execute(text(ins), {"e": "t_ok", "a": "max"})
    await _rejects(conn, ins, {"e": "t_bad", "a": "median"})


async def test_meter_claim_code_hash_unique_when_set(conn):
    ins = "INSERT INTO public.tb_meter (serial, claim_code_hash) VALUES (:s, :c)"
    await conn.execute(text(ins), {"s": "A", "c": None})
    await conn.execute(text(ins), {"s": "B", "c": None})  # NULLs may repeat
    await conn.execute(text(ins), {"s": "C", "c": "h"})
    await _rejects(conn, ins, {"s": "D", "c": "h"})


# --- foreign keys and cascades ---


async def test_home_delete_cascades(conn):
    uid, hid = await _user(conn), await _home(conn)
    await conn.execute(
        text("INSERT INTO public.tb_home_member (home_id, user_id, role) VALUES (:h, :u, 'owner')"),
        {"h": hid, "u": uid},
    )
    await conn.execute(
        text(
            "INSERT INTO public.tb_home_invite (home_id, code_hash, expires_at)"
            " VALUES (:h, 'k', now())"
        ),
        {"h": hid},
    )
    did = await _device(conn, hid)
    await conn.execute(
        text("INSERT INTO public.tb_device_alert_rule (device_id, kind) VALUES (:d, 'on')"),
        {"d": did},
    )
    await conn.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": hid})
    for table in ("home_member", "home_invite", "device", "device_alert_rule"):
        n = await conn.scalar(text(f"SELECT count(*) FROM public.{table}"))
        assert n == 0, table
    assert await conn.scalar(text("SELECT count(*) FROM public.tb_users WHERE id = :u"), {"u": uid})


async def test_meter_fk_to_home_blocks_delete(conn):
    hid = await _home(conn)
    await conn.execute(
        text("INSERT INTO public.tb_meter (serial, home_id) VALUES ('SN-FK', :h)"), {"h": hid}
    )
    await _rejects(conn, "DELETE FROM public.tb_home WHERE id = :h", {"h": hid})
    await _rejects(
        conn,
        "INSERT INTO public.tb_meter (serial, home_id) VALUES ('SN-FK2', :h)",
        {"h": -1},
    )


async def test_fk_columns_are_indexed(conn):
    rows = await conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
    names = {r[0] for r in rows}
    assert {
        "ix_device_home_id",
        "ix_device_alert_rule_device_id",
        "ix_home_invite_home_id",
        "ix_meter_home_id",
        "ix_device_merged_into_id",
        "ix_home_invite_used_by",
        "ix_home_invite_code_hash",
        "ix_meter_claim_code_hash",
    } <= names


# --- migration round trip ---


async def test_catalog_core_downgrade_upgrade(throwaway_dsn):
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.db.conftest import run_alembic

    q = text(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
    )
    engine = create_async_engine(throwaway_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            assert await c.scalar(q) == 8
        run_alembic(throwaway_dsn, "downgrade", "5f0b3c8a1d47")
        async with engine.connect() as c:
            assert await c.scalar(q) == 0
        run_alembic(throwaway_dsn, "upgrade", "head")
        async with engine.connect() as c:
            assert await c.scalar(q) == 8
            assert await c.scalar(text("SELECT count(*) FROM public.cat_device_type")) == 22
    finally:
        await engine.dispose()
