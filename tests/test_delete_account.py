import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, engine
from app.modules.auth.services import demo
from app.modules.energy.api import backfill_aggregates


@pytest.fixture
def keycloak(monkeypatch):
    """The realm's admin API: signs the service account in, records deletes, answers `status`."""
    monkeypatch.setattr(settings, "demo_admin_client_secret", "test-admin-secret")
    box = type("Box", (), {"deleted": [], "status": 204})()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"access_token": "t"})
        box.deleted.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(box.status)

    monkeypatch.setattr(demo, "_transport", httpx.MockTransport(handle))
    return box


async def scalar(sql: str, **params):
    async with SessionLocal() as s:
        return await s.scalar(text(sql), params)


async def sub_of(user_id) -> str:
    return await scalar("SELECT keycloak_sub FROM public.tb_users WHERE id = :u", u=user_id)


async def test_member_leaves_and_the_home_stays(client, make_member, keycloak):
    owner = await make_member()
    member = await make_member("member", home_id=owner.home_id)
    sub = await sub_of(member.user_id)

    r = await client.delete("/api/v1/users/me", headers=member.headers)

    assert r.status_code == 204
    assert keycloak.deleted == [sub]
    assert await scalar("SELECT count(*) FROM public.tb_users WHERE id = :u", u=member.user_id) == 0
    assert await scalar("SELECT count(*) FROM public.tb_home WHERE id = :h", h=owner.home_id) == 1


async def test_owner_with_other_members_deletes_nothing(client, make_member, keycloak):
    owner = await make_member()
    member = await make_member("member", home_id=owner.home_id)

    r = await client.delete("/api/v1/users/me", headers=owner.headers)

    assert r.status_code == 409
    assert r.json()["code"] == "home_has_members"
    assert keycloak.deleted == []
    assert await scalar("SELECT count(*) FROM public.tb_users WHERE id = :u", u=owner.user_id) == 1
    assert await scalar("SELECT count(*) FROM public.tb_home WHERE id = :h", h=owner.home_id) == 1
    assert await scalar("SELECT count(*) FROM public.tb_users WHERE id = :u", u=member.user_id) == 1


async def test_sole_owner_erases_the_home_its_readings_and_aggregates(
    client, make_member, keycloak
):
    owner = await make_member()
    day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=3)
    async with SessionLocal() as s, s.begin():
        sid = await s.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": owner.home_id},
        )
        for i in range(3):
            await s.execute(
                text(
                    "INSERT INTO public.tb_reading (series_id, ts, value, quality) "
                    "VALUES (:s, :t, 100, 0)"
                ),
                {"s": sid, "t": day + timedelta(minutes=i)},
            )
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await backfill_aggregates(c, day, day + timedelta(days=1))
    assert await scalar("SELECT count(*) FROM public.reading_1m WHERE series_id = :s", s=sid) == 3

    r = await client.delete("/api/v1/users/me", headers=owner.headers)

    assert r.status_code == 204
    assert len(keycloak.deleted) == 1
    for table in ("tb_reading", "tb_device_estimate", "reading_1m", "reading_1h", "reading_1d"):
        assert await scalar(f"SELECT count(*) FROM public.{table} WHERE series_id = :s", s=sid) == 0
    assert await scalar("SELECT count(*) FROM public.tb_home WHERE id = :h", h=owner.home_id) == 0
    assert await scalar("SELECT count(*) FROM public.tb_users WHERE id = :u", u=owner.user_id) == 0


async def _series_with_data(home_id, day, *, estimates=False):
    """A main series with 3 minutes of readings (and device estimates) on `day`, aggregated."""
    async with SessionLocal() as s, s.begin():
        sid = await s.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": home_id},
        )
        for table in ("tb_reading", "tb_device_estimate") if estimates else ("tb_reading",):
            for i in range(3):
                await s.execute(
                    text(f"INSERT INTO {table} (series_id, ts, value) VALUES (:s, :t, 100)"),
                    {"s": sid, "t": day + timedelta(minutes=i)},
                )
    return sid


async def test_totals_outlive_their_raw_rows_and_other_homes_keep_theirs(
    client, make_member, keycloak
):
    """Retention drops raw rows after 400 days but never the hourly and daily totals: they go too,
    and no other home's total changes."""
    owner, other = await make_member(), await make_member()
    day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=3)
    mine = await _series_with_data(owner.home_id, day, estimates=True)
    theirs = await _series_with_data(other.home_id, day)
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await backfill_aggregates(c, day, day + timedelta(days=1))
    async with SessionLocal() as s, s.begin():  # what retention does to the raw rows
        await s.execute(text("DELETE FROM public.tb_reading WHERE series_id = :s"), {"s": mine})
        await s.execute(
            text("DELETE FROM public.tb_device_estimate WHERE series_id = :s"), {"s": mine}
        )
    views = ("reading_1m", "reading_1h", "reading_1d", "device_estimate_1m", "device_estimate_1h")
    assert await scalar("SELECT count(*) FROM public.reading_1d WHERE series_id = :s", s=mine) == 1
    theirs_before = [
        await scalar(f"SELECT count(*) FROM public.reading_{v} WHERE series_id = :s", s=theirs)
        for v in ("1m", "1h", "1d")
    ]

    r = await client.delete("/api/v1/users/me", headers=owner.headers)

    assert r.status_code == 204
    for view in views:
        assert await scalar(f"SELECT count(*) FROM public.{view} WHERE series_id = :s", s=mine) == 0
    assert theirs_before == [
        await scalar(f"SELECT count(*) FROM public.reading_{v} WHERE series_id = :s", s=theirs)
        for v in ("1m", "1h", "1d")
    ]
    assert 0 not in theirs_before


async def test_a_home_with_a_meter_and_a_member_who_used_an_invite_can_still_be_erased(
    client, make_member, keycloak
):
    owner = await make_member()
    member = await make_member("member", home_id=owner.home_id)
    serial = f"test-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("INSERT INTO public.tb_meter (serial, home_id) VALUES (:n, :h)"),
            {"n": serial, "h": owner.home_id},
        )
        await s.execute(
            text(
                "INSERT INTO public.tb_home_invite (home_id, code_hash, expires_at, used_by) "
                "VALUES (:h, :c, now() + interval '1 day', :u)"
            ),
            {"h": owner.home_id, "c": uuid.uuid4().hex, "u": member.user_id},
        )
    try:
        # the member leaves: the invite they used stays, with nobody on it
        assert (await client.delete("/api/v1/users/me", headers=member.headers)).status_code == 204
        # the owner is now alone: the home goes, the meter hardware stays unclaimed
        assert (await client.delete("/api/v1/users/me", headers=owner.headers)).status_code == 204
        assert (
            await scalar("SELECT count(*) FROM public.tb_home WHERE id = :h", h=owner.home_id) == 0
        )
        assert (
            await scalar("SELECT home_id FROM public.tb_meter WHERE serial = :n", n=serial) is None
        )
    finally:
        async with SessionLocal() as s, s.begin():
            await s.execute(text("DELETE FROM public.tb_meter WHERE serial = :n"), {"n": serial})


async def test_compressed_readings_over_the_decompression_limit_are_erased(
    client, make_member, keycloak
):
    """Timescale refuses a DELETE that decompresses over 100000 rows unless the limit is lifted."""
    owner = await make_member()
    async with SessionLocal() as s, s.begin():
        sid = await s.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": owner.home_id},
        )
        await s.execute(
            text(
                "INSERT INTO public.tb_reading (series_id, ts, value, quality) "
                "SELECT :s, now() - interval '5 days' + i * interval '1 second', 100, 0 "
                "FROM generate_series(0, 119999) AS i"
            ),
            {"s": sid},
        )
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await c.execute(
            text(
                "SELECT compress_chunk(c, if_not_compressed => true) "
                "FROM show_chunks('public.tb_reading', older_than => now() - interval '1 day') c"
            )
        )

    r = await client.delete("/api/v1/users/me", headers=owner.headers)

    assert r.status_code == 204
    assert await scalar("SELECT count(*) FROM public.tb_reading WHERE series_id = :s", s=sid) == 0


async def test_without_the_admin_secret_nothing_is_erased(client, make_member, monkeypatch):
    monkeypatch.setattr(settings, "demo_admin_client_secret", "")
    owner = await make_member()

    r = await client.delete("/api/v1/users/me", headers=owner.headers)

    assert r.status_code == 503
    assert r.json()["code"] == "account_delete_unavailable"
    assert await scalar("SELECT count(*) FROM public.tb_users WHERE id = :u", u=owner.user_id) == 1
    assert await scalar("SELECT count(*) FROM public.tb_home WHERE id = :h", h=owner.home_id) == 1


async def test_keycloak_refusing_leaves_an_empty_account_that_can_ask_again(
    client, make_member, keycloak
):
    owner = await make_member()
    keycloak.status = 500

    r = await client.delete("/api/v1/users/me", headers=owner.headers)

    assert r.status_code == 503
    assert r.json()["code"] == "account_delete_unavailable"
    assert await scalar("SELECT count(*) FROM public.tb_home WHERE id = :h", h=owner.home_id) == 0

    keycloak.status = 204  # the same token signs in again to an empty profile and deletes it
    assert (await client.delete("/api/v1/users/me", headers=owner.headers)).status_code == 204


async def test_a_new_account_without_a_home_can_delete_itself(client, make_token, keycloak):
    headers = {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}

    assert (await client.delete("/api/v1/users/me", headers=headers)).status_code == 204
    assert len(keycloak.deleted) == 1
