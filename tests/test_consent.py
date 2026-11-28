import httpx
import pytest
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal


@pytest.fixture(autouse=True)
def enforced(monkeypatch):
    monkeypatch.setattr(settings, "consent_enforced", True)


async def rows(user_id, purpose):
    async with SessionLocal() as s:
        return (
            (
                await s.execute(
                    text(
                        "SELECT granted FROM public.tb_consent WHERE user_id = :u AND purpose = :p "
                        "ORDER BY created_at, id"
                    ),
                    {"u": user_id, "p": purpose},
                )
            )
            .scalars()
            .all()
        )


async def test_every_purpose_starts_off_and_each_change_adds_one_row(client, make_member):
    me = await make_member("owner", consent=())
    r = await client.get("/api/v1/users/me/consents", headers=me.headers)
    assert {c["purpose"]: c["granted"] for c in r.json()} == {
        "wappi": False,
        "voice": False,
        "email": False,
    }
    for granted in (True, False, True):
        r = await client.put(
            "/api/v1/users/me/consents/wappi", json={"granted": granted}, headers=me.headers
        )
        assert r.status_code == 200 and r.json()["granted"] is granted
    assert await rows(me.user_id, "wappi") == [True, False, True]
    bad = await client.put(
        "/api/v1/users/me/consents/ads", json={"granted": True}, headers=me.headers
    )
    assert bad.status_code == 422


async def test_without_consent_nothing_leaves(client, make_member, monkeypatch):
    from app.modules.copilot.services import llm

    me = await make_member("owner", consent=())
    calls = []
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: calls.append(r)), **kw),
    )
    monkeypatch.setattr(llm, "stream", lambda *a: (_ for _ in ()).throw(AssertionError("sent")))
    r = await client.post("/api/v1/copilot/chat", json={"question": "Xin chào"}, headers=me.headers)
    assert (r.status_code, r.json()["code"], r.json()["purpose"]) == (
        403,
        "consent_required",
        "wappi",
    )
    webm = {**me.headers, "Content-Type": "audio/webm"}
    r = await client.post("/api/v1/copilot/voice/transcribe", content=b"x", headers=webm)
    assert (r.status_code, r.json()["purpose"]) == (403, "voice")
    assert calls == []


async def test_withdrawing_blocks_at_once(client, make_member):
    me = await make_member("owner")  # agreed to wappi and voice
    url = "/api/v1/users/me/consents/wappi"
    assert (await client.put(url, json={"granted": False}, headers=me.headers)).status_code == 200
    r = await client.post("/api/v1/copilot/chat", json={"question": "Xin chào"}, headers=me.headers)
    assert r.status_code == 403


async def test_the_outbound_log_lists_my_last_30_days(client, make_member):
    from app.common import outbound

    me = await make_member("owner")
    other = await make_member("owner")
    await outbound.record("openrouter", "wappi", ["question"], "daily", user_id=me.user_id)
    await outbound.record("openweather", "weather", ["province location"], home_id=me.home_id)
    await outbound.record("openrouter", "wappi", ["question"], user_id=other.user_id)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_outbound_log (created_at, user_id, party, purpose, data) "
                "VALUES (now() - interval '31 days', :u, 'astralx', 'voice', '{x}')"
            ),
            {"u": me.user_id},
        )
    r = await client.get("/api/v1/users/me/outbound", headers=me.headers)
    assert r.status_code == 200
    got = [(x["party"], x["purpose"], x["data"], x["detail"]) for x in r.json()]
    assert sorted(got) == [
        ("openrouter", "wappi", ["question"], "daily"),
        ("openweather", "weather", ["province location"], None),
    ]
