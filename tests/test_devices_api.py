import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.modules.energy.api import backfill_aggregates
from app.modules.energy.services import runs

KETTLE_W = 2000.0


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def home(client, make_token):
    """A member's home: main meter + NILM kettle (one 3-minute boil ending 10 min ago) + fridge."""
    token = make_token(sub=str(uuid.uuid4()))
    me = (await client.get("/api/v1/users/me", headers=bearer(token))).json()
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    boil = [now - timedelta(minutes=m) for m in (13, 12, 11)]
    async with SessionLocal() as s, s.begin():
        hid = await s.scalar(text("INSERT INTO public.tb_home (name) VALUES ('Dev') RETURNING id"))
        await s.execute(
            text("INSERT INTO public.tb_home_member (home_id, user_id) VALUES (:h, :u)"),
            {"h": hid, "u": me["id"]},
        )
        main = await s.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": hid},
        )
        ids = {}
        for code, timeline in (("kettle", True), ("fridge_freezer", False)):
            did = await s.scalar(
                text(
                    "INSERT INTO public.tb_device (home_id, device_type_code, name, origin, "
                    "show_on_timeline) VALUES (:h, :c, :c, 'nilm', :t) RETURNING id"
                ),
                {"h": hid, "c": code, "t": timeline},
            )
            sid = await s.scalar(
                text(
                    "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
                    "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"
                ),
                {"h": hid, "d": did},
            )
            ids[code] = (did, sid)
        rows = []
        for minute in boil:  # four 15 s bins per minute
            rows += [
                (minute + timedelta(seconds=15 * i), ids["kettle"][1], KETTLE_W) for i in range(4)
            ]
        rows += [(now - timedelta(seconds=15), ids["fridge_freezer"][1], 80.0)]
        rows += [(boil[0], main, KETTLE_W + 80.0)]
        await s.execute(
            text(
                "INSERT INTO public.tb_device_estimate (ts, series_id, value) VALUES (:t, :s, :v)"
            ),
            [{"t": t, "s": sid, "v": v} for t, sid, v in rows if sid != main],
        )
        await s.execute(
            text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, :v)"),
            {"t": boil[0], "s": main, "v": KETTLE_W + 80.0},
        )
    # Rows older than an aggregate's watermark show after its next refresh (real-time aggregation
    # covers only newer buckets): refresh now, as the NILM worker does after writing history.
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await backfill_aggregates(c, now - timedelta(days=1), now + timedelta(minutes=1))
    yield token, hid, ids, now
    async with SessionLocal() as s, s.begin():
        await s.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": hid})


async def test_device_routes_require_a_token(client):
    for path in ("devices", f"devices/{uuid.uuid4()}", "activity"):
        assert (await client.get(f"/api/v1/energy/{path}")).status_code == 401


async def test_devices_list_power_now_today_and_week(client, home):
    token, _hid, ids, _now = home
    r = await client.get("/api/v1/energy/devices", headers=bearer(token))
    assert r.status_code == 200
    by_type = {d["type"]: d for d in r.json()}
    kettle, fridge = by_type["kettle"], by_type["fridge_freezer"]
    assert kettle["id"] == str(ids["kettle"][0])
    assert kettle["on"] is False and kettle["watts"] == 0.0  # the boil ended 10 minutes ago
    assert fridge["on"] is True and fridge["watts"] == 80.0
    boil_kwh = 3 * KETTLE_W / 60 / 1000  # 3 minutes at 2 kW
    assert len(kettle["week_kwh"]) == 7
    assert kettle["week_kwh"][-1] + kettle["week_kwh"][-2] == pytest.approx(boil_kwh, rel=1e-3)


async def test_device_detail_has_the_run_and_404s_for_another_home(
    client, home, make_token, make_member
):
    token, _hid, ids, now = home
    r = await client.get(f"/api/v1/energy/devices/{ids['kettle'][0]}", headers=bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert body["peak_w"] == KETTLE_W and body["avg_on_w"] == KETTLE_W
    assert [c["kwh"] for c in body["cycles"]] == [pytest.approx(0.1, rel=1e-3)]
    start = int((now - timedelta(minutes=13)).timestamp() * 1000)
    assert body["cycles"][0]["start"] == start
    assert body["cycles"][0]["end"] == start + 3 * 60_000
    assert body["power"] and all(set(p) == {"ts", "watts"} for p in body["power"])

    stranger = make_token(sub=str(uuid.uuid4()))
    other = await client.get(f"/api/v1/energy/devices/{ids['kettle'][0]}", headers=bearer(stranger))
    assert other.status_code == 404  # no home at all
    neighbour = await make_member("owner")  # a home of their own, not this one
    r = await client.get(f"/api/v1/energy/devices/{ids['kettle'][0]}", headers=neighbour.headers)
    assert r.status_code == 404 and r.json()["code"] == "device_not_found"
    missing = await client.get(f"/api/v1/energy/devices/{uuid.uuid4()}", headers=bearer(token))
    assert missing.status_code == 404 and missing.json()["code"] == "device_not_found"


async def test_activity_lists_timeline_devices_only(client, home):
    token, *_ = home
    r = await client.get("/api/v1/energy/activity", headers=bearer(token))
    assert r.status_code == 200
    assert [a["name"] for a in r.json()] == ["kettle"]  # the fridge is off the timeline


def test_runs_merge_short_pauses_drop_noise_and_keep_a_running_tail():
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    m = lambda i: t0 + timedelta(minutes=i)  # noqa: E731
    minutes = [
        (m(0), 2000.0, 33.0),
        (m(2), 2000.0, 33.0),
        (m(10), 30.0, 0.5),
        (m(20), 2000.0, 33.0),
    ]
    out = runs(minutes, 1000.0, now=m(21))
    assert [(c.start, c.end) for c in out] == [(m(0), m(3)), (m(20), None)]  # gap of 1 min merged
    assert runs([(m(0), 25.0, 0.4)], 20.0, now=m(30)) == []  # 0.4 Wh: noise
