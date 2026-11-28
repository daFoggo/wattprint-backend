import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.modules.energy.api import backfill_aggregates
from app.modules.energy.routes import dashboard
from app.modules.energy.services import daily_now, today_energy


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def member(client, make_token):
    """A user in a fresh home whose main meter read 100 W and 200 W in the last two minutes."""
    token = make_token(sub=str(uuid.uuid4()))
    me = await client.get("/api/v1/users/me", headers=bearer(token))
    assert me.status_code == 200
    now = datetime.now(UTC).replace(microsecond=0)
    async with SessionLocal() as session, session.begin():
        hid = await session.scalar(
            text("INSERT INTO public.tb_home (name) VALUES ('Energy API') RETURNING id")
        )
        sid = await session.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": hid},
        )
        await session.execute(
            text("INSERT INTO public.tb_home_member (home_id, user_id) VALUES (:h, :u)"),
            {"h": hid, "u": me.json()["id"]},
        )
        await session.execute(
            text(
                "INSERT INTO public.tb_reading (series_id, ts, value, quality) "
                "VALUES (:s, :a, 100, 0), (:s, :b, 200, 0)"
            ),
            {"s": sid, "a": now - timedelta(minutes=2), "b": now - timedelta(minutes=1)},
        )
    yield token, now
    async with SessionLocal() as session, session.begin():
        await session.execute(
            text("DELETE FROM public.tb_reading WHERE series_id = :s"), {"s": sid}
        )
        await session.execute(text("DELETE FROM public.tb_series WHERE series_id = :s"), {"s": sid})
        await session.execute(
            text("DELETE FROM public.tb_home_member WHERE home_id = :h"), {"h": hid}
        )
        await session.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": hid})


async def test_energy_routes_require_a_token(client):
    for path in (
        "overview",
        "stream",
        "series?since=2026-11-01T00:00:00Z&until=2026-11-02T00:00:00Z",
    ):
        assert (await client.get(f"/api/v1/energy/{path}")).status_code == 401


async def test_account_without_a_home_gets_404(client, make_token):
    r = await client.get("/api/v1/energy/overview", headers=bearer(make_token()))
    assert r.status_code == 404
    assert r.json()["code"] == "home_not_found"


async def test_overview_has_the_newest_reading(client, member):
    token, now = member
    r = await client.get("/api/v1/energy/overview", headers=bearer(token))
    assert r.status_code == 200
    assert r.json()["live"] == {
        "ts": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "watts": 200.0,
    }


async def test_series_covers_the_window(client, member):
    token, now = member
    params = {
        "since": (now - timedelta(hours=1)).isoformat(),
        "until": now.isoformat(),
        "max_points": 60,
    }
    r = await client.get("/api/v1/energy/series", headers=bearer(token), params=params)
    assert r.status_code == 200
    points = r.json()
    assert points and all(p["energy_wh"] >= 0 for p in points)


async def make_daily(client, token) -> tuple[uuid.UUID, uuid.UUID]:
    """The member's home and user ids, the member now seeing days only."""
    me = (await client.get("/api/v1/users/me", headers=bearer(token))).json()["id"]
    async with SessionLocal() as session, session.begin():
        home = await session.scalar(
            text(
                "UPDATE public.tb_home_member SET detail = 'daily' WHERE user_id = :u "
                "RETURNING home_id"
            ),
            {"u": me},
        )
    return home, uuid.UUID(me)


async def test_a_daily_member_gets_the_series_by_day_only(client, member):
    token, now = member
    home, _ = await make_daily(client, token)
    async with SessionLocal() as session, session.begin():
        await session.execute(  # yesterday, same time: a day already over
            text(
                "INSERT INTO public.tb_reading (series_id, ts, value, quality) "
                "SELECT series_id, :t, 300, 0 FROM public.tb_series WHERE home_id = :h"
            ),
            {"t": now - timedelta(days=1), "h": home},
        )
    local = (now - timedelta(days=1)).astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
    yesterday = local.replace(hour=0, minute=0, second=0, microsecond=0)
    async with engine.connect() as c:  # that day only: today stays real-time
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await backfill_aggregates(c, yesterday, yesterday + timedelta(days=1))
    params = {"since": (now - timedelta(days=2)).isoformat(), "until": now.isoformat()}
    r = await client.get("/api/v1/energy/series", headers=bearer(token), params=params)
    assert r.status_code == 200, r.text
    # one day bucket, never minutes, and not the running day (its total is the overview's)
    (point,) = r.json()
    assert point["ts"].endswith("T17:00:00Z") and point["energy_wh"] > 0
    assert point["coarsened"] is False
    assert datetime.fromisoformat(point["ts"]) < now - timedelta(hours=1)


def test_daily_now_is_the_last_6_hour_block():
    for at, block in (("13:13", "12:00"), ("05:59", "00:00"), ("18:00", "18:00")):
        t = datetime.fromisoformat(f"2026-11-20T{at}:00+07:00")
        assert daily_now(t) == datetime.fromisoformat(f"2026-11-20T{block}:00+07:00")


async def test_a_daily_member_reads_today_as_of_the_last_6_hour_block(client, member):
    from app.modules.insight.services.watches import measure

    token, _ = member
    full = (await client.get("/api/v1/energy/overview", headers=bearer(token))).json()
    assert full["today"]["kwh"] > 0  # the last two minutes count for a full member
    home, user = await make_daily(client, token)
    seen = (await client.get("/api/v1/energy/overview", headers=bearer(token))).json()
    async with SessionLocal() as s:
        block = await today_energy(s, home, daily_now(datetime.now(UTC)))
        watched = await measure(s, home, "today_kwh", datetime.now(UTC), user_id=user)
    assert seen["today"]["kwh"] == block.kwh < full["today"]["kwh"]
    assert float(watched) == round(block.kwh, 3)


async def test_series_rejects_naive_datetimes(client, member):
    token, _ = member
    params = {"since": "2026-11-01T00:00:00", "until": "2026-11-02T00:00:00"}
    r = await client.get("/api/v1/energy/series", headers=bearer(token), params=params)
    assert r.status_code == 422


async def test_stream_sends_the_backlog_oldest_first_then_closes(client, member, monkeypatch):
    token, _ = member
    # No real waiting: poll back to back and close after a moment.
    monkeypatch.setattr(dashboard, "STREAM_POLL_S", 0)
    monkeypatch.setattr(dashboard, "STREAM_MAX", timedelta(milliseconds=300))
    r = await client.get("/api/v1/energy/stream", headers=bearer(token))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [line for line in r.text.splitlines() if line.startswith("data: ")]
    assert ['"watts":100.0' in events[0], '"watts":200.0' in events[1]] == [True, True]
    assert len(events) == 2  # each sample once, though the stream polled many times
