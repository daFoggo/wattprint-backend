import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update

from app.config import settings
from app.database import SessionLocal
from app.modules.insight.models import Alert, Watch
from app.modules.insight.services import cancel_watch, check_due, create_watch, list_watches
from app.modules.insight.utils import WatchError

needs_copilot_db = pytest.mark.skipif(
    not settings.copilot_database_url, reason="COPILOT_DATABASE_URL is not set"
)
DEVICES = "SELECT count(*) FROM copilot_ro.device"  # scoped to the home by the token


async def _device(home_id, name="Tủ lạnh"):
    async with SessionLocal() as s, s.begin():
        return await s.scalar(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'fridge', :n, 'manual') RETURNING id"
            ),
            {"h": home_id, "n": name},
        )


async def _watch(me, now, **kw):
    args = {"metric": "sql", "op": "gt", "threshold": 0, "label": "Số thiết bị", "sql": DEVICES}
    async with SessionLocal() as s, s.begin():
        w, value = await create_watch(s, me.user_id, me.home_id, now=now, **(args | kw))
    return w, value


async def _row(watch_id):
    async with SessionLocal() as s:
        return await s.get(Watch, watch_id)


@needs_copilot_db
async def test_custom_watch_reads_only_its_home_and_fires_once(make_member, monkeypatch):
    from app.modules.insight.services import mail

    sent = []

    async def fake_send(to, subject, body):
        sent.append((to, subject))

    monkeypatch.setattr(mail, "send", fake_send)
    me = await make_member("owner")
    housemate = await make_member("member", home_id=me.home_id)
    other = await make_member("owner")
    await _device(other.home_id)  # another home's device never counts
    now = datetime.now(UTC)

    w, value = await _watch(me, now)
    assert value == 0
    assert (w.every_s, w.status) == (600, "active")

    await check_due(now)  # not due yet
    assert (await _row(w.id)).last_checked_at == w.last_checked_at

    await _device(me.home_id)
    later = now + timedelta(minutes=11)
    await check_due(later)
    row = await _row(w.id)
    assert (row.status, row.last_value, row.fired_at) == ("fired", 1, later)
    async with SessionLocal() as s:
        alert = await s.scalar(select(Alert).where(Alert.home_id == me.home_id))
    assert alert.kind == "watch_hit"
    assert alert.payload == {
        "watch_id": str(w.id),
        "label": "Số thiết bị",
        "op": "gt",
        "threshold": 0.0,
        "unit": "",
        "repeat": False,
        "value": 1.0,
    }

    await check_due(later + timedelta(hours=1))  # fired: never checked again
    assert (await _row(w.id)).last_checked_at == later

    await mail.mail_alerts(later)
    async with SessionLocal() as s:
        email = await s.scalar(
            text("SELECT email FROM public.tb_users WHERE id = :u"), {"u": me.user_id}
        )
    assert sent == [(email, "WattPrint: Số thiết bị đã vượt 0")]  # not the housemate
    assert housemate.user_id != me.user_id


@needs_copilot_db
@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT generate_series(1, 2)", "not_one_number"),
        ("SELECT 'abc'", "not_one_number"),
        ("SELECT 1 WHERE false", "not_one_number"),
    ],
)
async def test_custom_query_must_give_one_number(make_member, sql, code):
    me = await make_member("owner")
    with pytest.raises(WatchError) as e:
        await _watch(me, datetime.now(UTC), sql=sql)
    assert e.value.code == code


@needs_copilot_db
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT set_config('role', 'postgres', false)::int",  # take the superuser back
        "SELECT count(*) FROM public.tb_users",  # a table, not a copilot_ro view
        "SELECT count(*) FROM public.tb_watch",
    ],
)
async def test_custom_query_runs_as_the_read_only_copilot_role(make_member, sql):
    me = await make_member("owner")
    with pytest.raises(Exception, match="permission denied"):
        await _watch(me, datetime.now(UTC), sql=sql)


@needs_copilot_db
@pytest.mark.parametrize(("ai_detail", "want"), [(None, "daily"), ("hourly", "hourly")])
async def test_a_custom_query_reads_at_the_home_level(make_member, ai_detail, want):
    from app.modules.insight.services.watches import run_sql

    me = await make_member("owner", ai_detail=ai_detail)
    # 1 when the copilot views see hours for this home, 0 when they see days only
    got = await run_sql(me.home_id, "SELECT (copilot_ro.current_detail() = 'hourly')::int")
    assert got == (1 if want == "hourly" else 0)


@needs_copilot_db
async def test_a_daily_home_refuses_a_query_on_hours(make_member):
    from app.modules.insight.services.watches import run_sql

    me = await make_member("owner")  # the default level: daily
    with pytest.raises(WatchError) as e:
        await run_sql(me.home_id, "SELECT sum(energy_wh) FROM copilot_ro.reading_1h")
    assert e.value.code == "needs_hourly"


@needs_copilot_db
async def test_refuses_what_is_already_past_and_more_than_ten(make_member):
    me = await make_member("owner")
    now = datetime.now(UTC)
    with pytest.raises(WatchError) as e:
        await _watch(me, now, op="lt", threshold=1)
    assert (e.value.code, e.value.value) == ("already_crossed", 0)

    for _ in range(10):
        await _watch(me, now)
    with pytest.raises(WatchError) as e:
        await _watch(me, now)
    assert e.value.code == "too_many"


async def test_a_failing_watch_breaks_after_three_tries_and_says_so(make_member):
    me = await make_member("owner")
    now = datetime.now(UTC)
    async with SessionLocal() as s, s.begin():
        w = Watch(
            user_id=me.user_id,
            home_id=me.home_id,
            metric="bill_vnd",  # this home has no tariff plan: every check fails
            label="Tiền điện kỳ này",
            op="gt",
            threshold=1_000_000,
            unit="vnd",
            every_s=3600,
            ends_at=now + timedelta(days=5),
            next_check_at=now,
        )
        s.add(w)
    for hours in range(3):
        await check_due(now + timedelta(hours=hours))
    row = await _row(w.id)
    assert (row.status, row.fails) == ("broken", 3)
    async with SessionLocal() as s:
        kinds = list(await s.scalars(select(Alert.kind).where(Alert.home_id == me.home_id)))
    assert kinds == ["watch_broken"]


async def test_an_ended_watch_expires_quietly_and_cancel_is_the_owners(make_member):
    me = await make_member("owner")
    housemate = await make_member("member", home_id=me.home_id)
    now = datetime.now(UTC)
    async with SessionLocal() as s, s.begin():
        old, live = (
            Watch(
                user_id=me.user_id,
                home_id=me.home_id,
                metric="power_w",
                label=label,
                op="gt",
                threshold=3000,
                unit="w",
                every_s=60,
                ends_at=ends,
                next_check_at=now,
            )
            for label, ends in (("old", now), ("live", now + timedelta(days=1)))
        )
        s.add_all([old, live])
    await check_due(now)
    assert (await _row(old.id)).status == "expired"

    async with SessionLocal() as s, s.begin():
        assert not await cancel_watch(s, housemate.user_id, me.home_id, live.id)
        assert await cancel_watch(s, me.user_id, me.home_id, live.id)
        assert [w.label for w in await list_watches(s, me.user_id, me.home_id)] == [
            "live",
            "old",
        ]
    assert (await _row(live.id)).status == "cancelled"
    async with SessionLocal() as s:
        assert await s.scalar(select(Alert.id).where(Alert.home_id == me.home_id)) is None

    # A broken watch is still listed, so it can be cancelled too; an expired one stays expired.
    async with SessionLocal() as s, s.begin():
        await s.execute(update(Watch).where(Watch.id == live.id).values(status="broken"))
        assert await cancel_watch(s, me.user_id, me.home_id, live.id)
        assert await cancel_watch(s, me.user_id, me.home_id, old.id)
    assert (await _row(live.id)).status == "cancelled"
    assert (await _row(old.id)).status == "expired"


def _text2sql(monkeypatch, out):
    import uuid

    import httpx

    from app.modules.copilot.services import tools

    sent = {}

    def reply(request):
        sent.update(path=request.url.path, body=json.loads(request.content))
        return httpx.Response(200, json=out)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        tools.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(reply), **kw)
    )
    monkeypatch.setattr(tools.settings, "text2sql_connection_id", str(uuid.uuid4()))
    return tools, sent


def _chat_out(*steps, clarification=None):
    return {
        "answer": "",
        "clarification_question": clarification,
        "preprocess": {},
        "answers": [{"position": 1, "question": "q", "answer": "", "steps": list(steps)}],
    }


@needs_copilot_db
async def test_wappi_saves_a_custom_watch_from_text2sqls_query(make_member, monkeypatch):
    tools, sent = _text2sql(
        monkeypatch,
        _chat_out(
            {"tool": "run_sql", "sql": "SELECT 1 / 0", "error": "division by zero"},
            {"tool": "run_sql", "sql": DEVICES, "rows": [[0]]},
        ),
    )
    me = await make_member("owner")
    async with SessionLocal() as s:
        ctx = tools.Ctx(s, me.home_id, datetime.now(UTC), "vi", user_id=me.user_id, question="q")
        out = await tools.create_watch_tool(
            ctx, "custom", "gt", 2, "Số thiết bị", question="Nhà có bao nhiêu thiết bị?"
        )
    assert sent["path"] == tools.T2S_CHAT and sent["body"]["scope_token"]
    assert out.data["saved"] and out.data["value_now"] == 0 and out.sql == DEVICES
    assert [(w.kind, w.id, w.value) for w in out.widgets] == [("watch", out.data["watch_id"], 0)]
    async with SessionLocal() as s:
        w = await s.get(Watch, uuid.UUID(out.data["watch_id"]))
    assert (w.metric, w.sql_text, w.utterance, w.user_id) == ("sql", DEVICES, "q", me.user_id)


async def test_wappi_passes_text2sqls_question_back_and_names_devices(make_member, monkeypatch):
    tools, _ = _text2sql(monkeypatch, _chat_out(clarification="Thiết bị nào?"))
    me = await make_member("owner")
    await _device(me.home_id, "Tủ lạnh")
    await _device(me.home_id, "Tủ đông")
    async with SessionLocal() as s:
        ctx = tools.Ctx(s, me.home_id, datetime.now(UTC), "vi", user_id=me.user_id)
        asked = await tools.create_watch_tool(ctx, "custom", "gt", 1, "x", question="tủ?")
        vague = await tools.create_watch_tool(ctx, "device_kwh_today", "gt", 1, "x", device="tủ")
        nobody = await tools.create_watch_tool(
            tools.Ctx(s, me.home_id, datetime.now(UTC), "vi"), "power_w", "gt", 1, "x"
        )
    assert asked.data == {"error": "needs clarification: Thiết bị nào?"}
    assert sorted(vague.data["devices"]) == ["Tủ lạnh", "Tủ đông"]
    assert nobody.data == {"error": "no user to notify"}


async def test_watch_api_lists_and_cancels_only_the_users_own(client, make_member):
    me = await make_member("owner")
    housemate = await make_member("member", home_id=me.home_id)
    now = datetime.now(UTC)
    async with SessionLocal() as s, s.begin():
        w = Watch(
            user_id=me.user_id,
            home_id=me.home_id,
            metric="power_w",
            label="Công suất",
            op="gt",
            threshold=3000,
            unit="w",
            every_s=60,
            ends_at=now + timedelta(days=1),
        )
        s.add(w)
        await s.flush()
        await s.execute(
            text(
                "INSERT INTO public.tb_alert (home_id, kind, severity, ts, payload, dedup_key) "
                "VALUES (:h, 'watch_hit', 'warning', now(), :p, 'watch:x')"
            ),
            {"h": me.home_id, "p": json.dumps({"label": "Công suất", "op": "gt", "value": 3200})},
        )

    r = await client.get("/api/v1/insights/watches", headers=me.headers)
    assert r.status_code == 200
    assert [(x["label"], x["status"], x["threshold"]) for x in r.json()] == [
        ("Công suất", "active", "3000.000")
    ]
    assert (await client.get("/api/v1/insights/watches", headers=housemate.headers)).json() == []
    r = await client.delete(f"/api/v1/insights/watches/{w.id}", headers=housemate.headers)
    assert (r.status_code, r.json()["code"]) == (404, "watch_not_found")
    r = await client.delete(f"/api/v1/insights/watches/{w.id}", headers=me.headers)
    assert r.status_code == 204
    assert (await _row(w.id)).status == "cancelled"

    alerts = (await client.get("/api/v1/insights/alerts", headers=housemate.headers)).json()
    assert alerts[0]["payload"] == {"label": "Công suất", "op": "gt", "value": 3200.0}


async def test_power_from_a_meter_that_stopped_is_no_value(make_member, monkeypatch):
    from app.modules.energy.api import LatestPower
    from app.modules.insight.services import watches

    me = await make_member("owner")
    now = datetime.now(UTC)
    for age, expected in ((timedelta(minutes=2), 290), (timedelta(hours=1), None)):

        async def latest(s, home_id, at, age=age):
            return LatestPower(now - age, 290.0)

        monkeypatch.setattr(watches, "latest_power", latest)
        async with SessionLocal() as s:
            assert await watches.measure(s, me.home_id, "power_w", now) == expected


async def test_post_creates_and_reads_back(client, make_member, monkeypatch):
    monkeypatch.setattr("app.modules.insight.services.watches.measure", _value(None))
    me = await make_member("owner")
    body = {"metric": "power_w", "op": "gt", "threshold": 50000, "label": "Công suất"}
    r = await client.post("/api/v1/insights/watches", json=body, headers=me.headers)
    assert r.status_code == 201, r.text
    assert (r.json()["label"], r.json()["status"], r.json()["value_now"]) == (
        "Công suất",
        "active",
        None,
    )
    listed = (await client.get("/api/v1/insights/watches", headers=me.headers)).json()
    assert [(w["id"], w["device_id"]) for w in listed] == [(r.json()["id"], None)]


async def test_post_maps_refusals(client, make_member, monkeypatch):
    monkeypatch.setattr("app.modules.insight.services.watches.measure", _value(10))
    me = await make_member("owner")
    url, h = "/api/v1/insights/watches", me.headers
    # A one-off alert already past is refused; a repeating one fires on its first check instead.
    body = {"metric": "power_w", "op": "gt", "threshold": 5, "label": "Công suất", "repeat": False}
    r = await client.post(url, json=body, headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "already_crossed"
    assert float(r.json()["value_now"]) == 10
    for _ in range(10):
        r = await client.post(url, json={**body, "threshold": 50}, headers=h)
        assert r.status_code == 201
    r = await client.post(url, json={**body, "threshold": 50}, headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "too_many")
    r = await client.post(url, json={**body, "metric": "sql"}, headers=h)
    assert r.status_code == 422


async def test_post_refuses_other_homes_device(client, make_member, monkeypatch):
    monkeypatch.setattr("app.modules.insight.services.watches.measure", _value(0))
    me = await make_member("owner")
    stranger = await make_member("owner")
    theirs = await _device(stranger.home_id)
    body = {"metric": "device_kwh_today", "op": "gt", "threshold": 5, "label": "Tủ lạnh"}
    r = await client.post(
        "/api/v1/insights/watches", json={**body, "device_id": str(theirs)}, headers=me.headers
    )
    assert (r.status_code, r.json()["code"]) == (422, "no_device")


def _value(v):
    async def measure(*_args, **_kw):
        return None if v is None else Decimal(v)

    return measure


async def test_device_event_watches_need_a_device_and_repeat(client, make_member):
    me = await make_member("owner")
    fridge = await _device(me.home_id)
    url, h = "/api/v1/insights/watches", me.headers
    for metric, threshold in (("device_on", 0), ("device_off", 0), ("device_run_min", 90)):
        body = {"metric": metric, "op": "gt", "threshold": threshold, "label": "Tủ lạnh"}
        r = await client.post(url, json={**body, "device_id": str(fridge)}, headers=h)
        assert r.status_code == 201, r.text
        assert (r.json()["repeat"], r.json()["device_id"]) == (True, str(fridge))
    r = await client.post(url, json={**body, "metric": "device_power_w"}, headers=h)
    assert (r.status_code, r.json()["code"]) == (422, "no_device")


async def test_wappi_sets_a_repeating_device_run_alert(make_member):
    from app.modules.copilot.services import tools

    me = await make_member("owner")
    await _device(me.home_id, name="Máy giặt")
    async with SessionLocal() as s:
        ctx = tools.Ctx(s, me.home_id, datetime.now(UTC), "vi", user_id=me.user_id, question="q")
        out = await tools.create_watch_tool(
            ctx, "device_off", "gt", 0, "Máy giặt tắt", device="máy giặt"
        )
    assert out.data["saved"], out.data
    async with SessionLocal() as s:
        w = await s.get(Watch, uuid.UUID(out.data["watch_id"]))
    assert (w.metric, w.repeat, w.device_id is not None) == ("device_off", True, True)
