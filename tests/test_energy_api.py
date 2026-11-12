import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.modules.energy.routes import dashboard


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
