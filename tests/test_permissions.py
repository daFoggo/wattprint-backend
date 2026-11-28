# Permission matrix: every API operation x seven actors, one expected status per cell (spec R4.6).
# PERMISSION_MATRIX_OUT=<file> also writes what came back (scripts/print_permission_matrix.py).

import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.main import app

# Display order. The owner runs last so its own deletes cannot hide another actor's result.
ACTORS = ("anonymous", "other_owner", "viewer", "daily_member", "member", "owner", "admin")
RUN_ORDER = ("anonymous", "other_owner", "viewer", "daily_member", "member", "admin", "owner")

NOW = datetime.now(UTC)
SINCE, UNTIL = (NOW - timedelta(hours=2)).isoformat(), NOW.isoformat()

# (method, path) -> request extras. Path ids are filled from the world below.
REQUESTS: dict[tuple[str, str], dict] = {
    ("GET", "/api/v1/health"): {},
    ("GET", "/api/v1/users/me"): {},
    ("DELETE", "/api/v1/users/me"): {},
    ("GET", "/api/v1/users/me/preferences"): {},
    ("PATCH", "/api/v1/users/me/preferences"): {"json": {"weekly_summary": False}},
    ("GET", "/api/v1/users"): {},
    ("GET", "/api/v1/users/me/consents"): {},
    ("PUT", "/api/v1/users/me/consents/{purpose}"): {"json": {"granted": True}},
    ("GET", "/api/v1/users/me/outbound"): {},
    ("GET", "/api/v1/demo/homes"): {},
    ("POST", "/api/v1/demo/homes/{key}/view"): {},
    ("POST", "/api/v1/demo/homes/{key}/guest"): {},
    ("GET", "/api/v1/homes/current"): {},
    ("GET", "/api/v1/homes/current/privacy"): {},
    ("DELETE", "/api/v1/homes/current/history"): {},
    ("PATCH", "/api/v1/homes/current"): {"json": {"name": "Nhà thử quyền"}},
    ("GET", "/api/v1/homes/provinces"): {},
    ("POST", "/api/v1/homes/current/invites"): {},
    ("POST", "/api/v1/homes/invites/accept"): {"json": {"code": "NOSUCHCODE"}},
    ("GET", "/api/v1/homes/current/members"): {},
    ("PATCH", "/api/v1/homes/current/members/{user_id}"): {"json": {"detail": "full"}},
    ("DELETE", "/api/v1/homes/current/members/{user_id}"): {},
    ("DELETE", "/api/v1/homes/current/membership"): {},
    ("GET", "/api/v1/energy/overview"): {},
    ("GET", "/api/v1/energy/series"): {"params": {"since": SINCE, "until": UNTIL}},
    ("GET", "/api/v1/energy/stream"): {},
    ("GET", "/api/v1/energy/devices"): {},
    ("GET", "/api/v1/energy/devices/{device_id}"): {},
    ("GET", "/api/v1/energy/activity"): {},
    ("GET", "/api/v1/energy/weather"): {},
    ("GET", "/api/v1/expected"): {"params": {"from": SINCE, "to": UNTIL}},
    ("GET", "/api/v1/billing/current"): {},
    ("GET", "/api/v1/billing/history"): {},
    ("GET", "/api/v1/billing/forecast"): {},
    ("GET", "/api/v1/billing/devices/forecast"): {},
    ("GET", "/api/v1/insights/alerts"): {},
    ("PATCH", "/api/v1/insights/alerts/{alert_id}"): {"json": {"status": "acknowledged"}},
    ("POST", "/api/v1/insights/alerts/{alert_id}/feedback"): {"json": {"verdict": "useful"}},
    ("GET", "/api/v1/insights/cohort"): {},
    ("POST", "/api/v1/insights/plans"): {
        "json": {"start_on": date.today().isoformat(), "actions": []}
    },
    ("GET", "/api/v1/insights/plans/basis"): {},
    ("GET", "/api/v1/insights/plans/history"): {},
    ("GET", "/api/v1/insights/plans/current"): {},
    ("DELETE", "/api/v1/insights/plans/current"): {},
    ("GET", "/api/v1/insights/plans/{plan_id}"): {},
    ("GET", "/api/v1/insights/watches"): {},
    ("POST", "/api/v1/insights/watches"): {
        "json": {"metric": "today_kwh", "op": "gt", "threshold": 5, "label": "Thử quyền"}
    },
    ("DELETE", "/api/v1/insights/watches/{watch_id}"): {},
    ("POST", "/api/v1/copilot/chat"): {"json": {"question": "Xin chào"}},
    ("GET", "/api/v1/copilot/conversations"): {},
    ("DELETE", "/api/v1/copilot/conversations"): {},
    ("GET", "/api/v1/copilot/conversations/{conversation_id}"): {},
    ("PATCH", "/api/v1/copilot/conversations/{conversation_id}"): {"json": {"title": "Đổi"}},
    ("DELETE", "/api/v1/copilot/conversations/{conversation_id}"): {},
    ("PUT", "/api/v1/copilot/messages/{message_id}/feedback"): {"json": {"value": "up"}},
    ("POST", "/api/v1/copilot/voice/transcribe"): {
        "content": b"opus",
        "headers": {"Content-Type": "audio/webm;codecs=opus"},
    },
    ("GET", "/api/v1/copilot/messages/{message_id}/speech"): {},
}

# Expected status per actor, in ACTORS order. The owner's 404 on forecast, basis and cohort means
# "not enough data" (a week of readings, ten homes), not a refusal: those routes read only the
# caller's own home. A cell that changes on purpose changes here, in the same commit.
EXPECTED: dict[tuple[str, str], tuple[int, ...]] = {
    ("GET", "/api/v1/billing/current"): (401, 200, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/billing/devices/forecast"): (401, 404, 404, 404, 404, 404, 404),
    ("GET", "/api/v1/billing/forecast"): (401, 404, 404, 404, 404, 404, 404),
    ("GET", "/api/v1/billing/history"): (401, 200, 200, 200, 200, 200, 404),
    ("POST", "/api/v1/copilot/chat"): (401, 200, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/copilot/conversations"): (401, 200, 200, 200, 200, 200, 404),
    ("DELETE", "/api/v1/copilot/conversations/{conversation_id}"): (
        401,
        404,
        404,
        404,
        404,
        204,
        404,
    ),
    ("GET", "/api/v1/copilot/conversations/{conversation_id}"): (401, 404, 404, 404, 404, 200, 404),
    ("PATCH", "/api/v1/copilot/conversations/{conversation_id}"): (
        401,
        404,
        404,
        404,
        404,
        200,
        404,
    ),
    ("PUT", "/api/v1/copilot/messages/{message_id}/feedback"): (401, 404, 404, 404, 404, 204, 404),
    ("GET", "/api/v1/copilot/messages/{message_id}/speech"): (401, 404, 404, 404, 404, 200, 404),
    ("POST", "/api/v1/copilot/voice/transcribe"): (401, 200, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/demo/homes"): (200, 200, 200, 200, 200, 200, 200),
    ("POST", "/api/v1/demo/homes/{key}/guest"): (403, 403, 403, 403, 403, 403, 403),
    ("POST", "/api/v1/demo/homes/{key}/view"): (401, 404, 404, 404, 404, 404, 404),
    ("GET", "/api/v1/energy/activity"): (401, 200, 200, 403, 200, 200, 404),
    ("GET", "/api/v1/energy/devices"): (401, 200, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/energy/devices/{device_id}"): (401, 404, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/energy/overview"): (401, 200, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/energy/series"): (401, 200, 200, 200, 200, 200, 404),  # daily: by day
    ("GET", "/api/v1/energy/stream"): (401, 200, 200, 403, 200, 200, 404),
    ("GET", "/api/v1/energy/weather"): (401, 200, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/expected"): (401, 200, 200, 403, 200, 200, 404),
    ("GET", "/api/v1/health"): (200, 200, 200, 200, 200, 200, 200),
    ("GET", "/api/v1/homes/current"): (401, 200, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/homes/current/privacy"): (401, 200, 200, 200, 200, 200, 404),
    ("PATCH", "/api/v1/homes/current"): (401, 200, 403, 403, 403, 200, 404),
    ("GET", "/api/v1/homes/provinces"): (200, 200, 200, 200, 200, 200, 200),
    ("GET", "/api/v1/insights/alerts"): (401, 200, 200, 200, 200, 200, 404),
    ("PATCH", "/api/v1/insights/alerts/{alert_id}"): (401, 404, 403, 204, 204, 204, 404),
    ("POST", "/api/v1/insights/alerts/{alert_id}/feedback"): (401, 404, 403, 204, 204, 204, 404),
    ("GET", "/api/v1/insights/cohort"): (401, 404, 404, 404, 404, 404, 404),
    ("POST", "/api/v1/insights/plans"): (401, 422, 409, 409, 409, 409, 404),
    ("GET", "/api/v1/insights/plans/basis"): (401, 422, 422, 422, 422, 422, 404),
    ("DELETE", "/api/v1/insights/plans/current"): (401, 404, 204, 204, 204, 204, 404),
    ("GET", "/api/v1/insights/plans/current"): (401, 404, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/insights/plans/history"): (401, 200, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/insights/plans/{plan_id}"): (401, 404, 200, 200, 200, 200, 404),
    ("GET", "/api/v1/insights/watches"): (401, 200, 200, 200, 200, 200, 404),
    ("POST", "/api/v1/insights/watches"): (401, 201, 403, 201, 201, 201, 404),
    ("DELETE", "/api/v1/insights/watches/{watch_id}"): (401, 404, 403, 404, 404, 204, 404),
    ("GET", "/api/v1/users"): (401, 403, 403, 403, 403, 403, 200),
    ("DELETE", "/api/v1/users/me"): (401, 204, 204, 204, 204, 204, 204),
    ("GET", "/api/v1/users/me"): (401, 200, 200, 200, 200, 200, 200),
    ("GET", "/api/v1/users/me/preferences"): (401, 200, 200, 200, 200, 200, 200),
    ("PATCH", "/api/v1/users/me/preferences"): (401, 200, 200, 200, 200, 200, 200),
    ("GET", "/api/v1/users/me/consents"): (401, 200, 200, 200, 200, 200, 200),
    ("PUT", "/api/v1/users/me/consents/{purpose}"): (401, 200, 200, 200, 200, 200, 200),
    ("GET", "/api/v1/users/me/outbound"): (401, 200, 200, 200, 200, 200, 200),
    ("DELETE", "/api/v1/homes/current/history"): (401, 204, 403, 403, 403, 204, 404),
    ("DELETE", "/api/v1/copilot/conversations"): (401, 204, 204, 204, 204, 204, 404),
    ("POST", "/api/v1/homes/current/invites"): (401, 201, 403, 403, 403, 201, 404),
    ("POST", "/api/v1/homes/invites/accept"): (401, 404, 404, 404, 404, 404, 404),
    ("GET", "/api/v1/homes/current/members"): (401, 200, 403, 200, 200, 200, 404),
    ("PATCH", "/api/v1/homes/current/members/{user_id}"): (401, 404, 403, 403, 403, 204, 404),
    ("DELETE", "/api/v1/homes/current/members/{user_id}"): (401, 404, 403, 403, 403, 204, 404),
    ("DELETE", "/api/v1/homes/current/membership"): (401, 403, 403, 204, 204, 403, 404),
}


@pytest.fixture
def stubs(monkeypatch):
    """No call leaves the test: the LLM, the guard, voice and Keycloak answer locally."""
    from app.modules.auth.services import demo
    from app.modules.copilot import services as copilot_services
    from app.modules.copilot.services import guard, llm, voice
    from app.modules.energy.routes import dashboard
    from app.modules.energy.services import weather

    async def stream(messages, tools, turn):
        turn.usage = {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0}
        turn.text += "Chào."
        yield "Chào."

    async def safe(question):
        return None

    async def transcribe(audio, kind, lang):
        return {"text": "xin chào", "language": "vietnamese", "duration": 1.0}

    async def speak(client, words):
        return b"audio"

    async def forecast(lat, lon, lang):
        now = {"dt": 1_763_500_000, "main": {"temp": 27, "feels_like": 30, "humidity": 70}}
        sky = [{"description": "nắng", "icon": "01d"}]
        slot = {"dt": now["dt"], "main": {"temp": 27}, "pop": 0.1, "weather": sky}
        return weather.parse({**now, "wind": {"speed": 2}, "weather": sky}, {"list": [slot]})

    def keycloak(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":  # the service account signs in
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(204)

    monkeypatch.setattr(llm, "stream", stream)
    monkeypatch.setattr(guard, "unsafe", safe)
    monkeypatch.setattr(settings, "astralx_api_key", "k")
    monkeypatch.setattr(copilot_services, "transcribe", transcribe)
    monkeypatch.setattr(voice, "_voice", speak)
    monkeypatch.setattr(dashboard, "STREAM_POLL_S", 0)
    monkeypatch.setattr(dashboard, "STREAM_MAX", timedelta(milliseconds=50))
    monkeypatch.setattr(settings, "demo_admin_client_secret", "test-admin-secret")
    monkeypatch.setattr(demo, "_transport", httpx.MockTransport(keycloak))
    monkeypatch.setattr(settings, "openweather_api_key", "k")
    monkeypatch.setattr(weather, "_fetch", forecast)
    weather._cache.clear()


@pytest.fixture
async def world(client, make_member, make_token, stubs):
    """Home A: an owner, a member, a demo-style viewer. Home B's owner. An admin. No token."""
    home = {"tariff_plan_code": "vn_residential", "province_code": "79"}
    owner = await make_member("owner", **home)
    member = await make_member("member", home_id=owner.home_id)
    daily = await make_member("member", home_id=owner.home_id)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("UPDATE public.tb_home_member SET detail = 'daily' WHERE user_id = :u"),
            {"u": daily.user_id},
        )
    viewer = await make_member("viewer", home_id=owner.home_id)
    other = await make_member("owner", **home)
    admin_token = make_token(roles=["admin"])
    admin = {"Authorization": f"Bearer {admin_token}"}
    assert (await client.get("/api/v1/users/me", headers=admin)).status_code == 200
    h, u = owner.home_id, owner.user_id
    async with SessionLocal() as s, s.begin():

        async def one(sql, **values):
            return await s.scalar(text(sql), {"h": h, "u": u, **values})

        ids = {
            "device_id": await one(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'kettle', 'Ấm siêu tốc', 'nilm') RETURNING id"
            ),
            "alert_id": await one(
                "INSERT INTO public.tb_alert (home_id, kind, severity, ts, payload, dedup_key) "
                "VALUES (:h, 'usage_anomaly', 'warning', now(), '{}', :k) RETURNING id",
                k=f"perm:{uuid.uuid4()}",
            ),
            "plan_id": await one(
                "INSERT INTO public.tb_savings_plan (user_id, home_id, start_on, end_on, "
                "model_version, forecast_kwh, actions) VALUES (:u, :h, current_date, "
                "current_date + 29, 'holdout-x', 400, '[]') RETURNING id"
            ),
            "watch_id": await one(
                "INSERT INTO public.tb_watch (user_id, home_id, metric, op, threshold, label, "
                "every_s, ends_at) VALUES (:u, :h, 'today_kwh', 'gt', 5, 'Thử', 300, "
                "now() + interval '1 day') RETURNING id"
            ),
            "conversation_id": await one(
                "INSERT INTO ai.ai_conversation (home_id, user_id) VALUES (:h, :u) RETURNING id"
            ),
        }
        await one(  # what NILM found: device detail lists only devices with an estimated series
            "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
            "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id",
            d=ids["device_id"],
        )
        for person in (
            member,
            daily,
            viewer,
        ):  # each has a plan of their own: plan cells then show the
            await one(  # permission check, not "no plan yet"
                "INSERT INTO public.tb_savings_plan (user_id, home_id, start_on, end_on, "
                "model_version, forecast_kwh, actions) VALUES (:p, :h, current_date, "
                "current_date + 29, 'holdout-x', 400, '[]') RETURNING id",
                p=person.user_id,
            )
        ids["message_id"] = await one(
            "INSERT INTO ai.ai_message (conversation_id, role, content) "
            "VALUES (:c, 'assistant', 'Hôm qua nhà bạn dùng 9 kWh.') RETURNING id",
            c=ids["conversation_id"],
        )
    ids["key"] = "not-a-demo-home"
    ids["purpose"] = "wappi"
    ids["user_id"] = member.user_id
    headers = {
        "anonymous": {},
        "other_owner": other.headers,
        "viewer": viewer.headers,
        "daily_member": daily.headers,
        "member": member.headers,
        "owner": owner.headers,
        "admin": admin,
    }
    return headers, {k: str(v) for k, v in ids.items()}


def operations() -> set[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return {(m.upper(), p) for p, ops in paths.items() for m in ops}


def test_every_operation_has_a_row():
    assert operations() == set(REQUESTS), "a new route needs its row in REQUESTS and EXPECTED"
    assert set(EXPECTED) == set(REQUESTS)


async def probe(client, world, method, path) -> dict[str, int]:
    headers, ids = world
    extra = REQUESTS[(method, path)]
    url = path.format(**ids)
    got = {}
    for actor in RUN_ORDER:
        r = await client.request(
            method,
            url,
            params=extra.get("params"),
            json=extra.get("json"),
            content=extra.get("content"),
            headers={**headers[actor], **extra.get("headers", {})},
        )
        got[actor] = r.status_code
    return {a: got[a] for a in ACTORS}


def _record(method, path, got):
    out = os.environ.get("PERMISSION_MATRIX_OUT")
    if out:
        with open(out, "a") as f:
            f.write(json.dumps({"method": method, "path": path, "got": got}) + "\n")


@pytest.mark.parametrize(("method", "path"), sorted(REQUESTS, key=lambda k: (k[1], k[0])))
async def test_permission_matrix(client, world, method, path):
    got = await probe(client, world, method, path)
    _record(method, path, got)
    want = dict(zip(ACTORS, EXPECTED[(method, path)], strict=True))
    assert got == want
