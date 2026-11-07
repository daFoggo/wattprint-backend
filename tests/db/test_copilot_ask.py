"""Seam 1: the Copilot HTTP API on the demo home, with a scripted chat model and fake embedder.

The model is replaced through the graph's runtime context; it may only pick device types the
linking step offered it (`typed` fails otherwise), so these tests also check word linking. The
questions reach their skill through the vector search over the synced catalog.
"Today" is pinned to 5 Nov 2026; the dump covers 29 Oct .. 4 Nov.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.copilot.agents.base_agent import CopilotContext
from app.database import get_session
from app.main import app
from app.models import ToolCall
from app.routers.copilot import get_copilot_context
from app.security import create_access_token
from tests.db.conftest import DEMO_TODAY, FakeChatModel, FakeEmbedder

YESTERDAY = "2026-11-04"
WEEK = ("2026-10-29", "2026-11-04")


def usage(**kw):
    return [("query_usage", kw)]


def typed(code: str, **kw):
    """A query on a device type, which must be among the linked terms."""

    def calls(payload):
        codes = {t["ref"] for t in payload["linked_terms"] if t["kind"] == "device_type"}
        assert code in codes, (code, payload["linked_terms"])
        return usage(device_type_codes=[code], **kw)

    return calls


SCRIPT = {
    "Hôm qua nhà tôi dùng bao nhiêu điện?": usage(start=YESTERDAY, end=YESTERDAY),
    "Ngày nào tuần qua dùng nhiều điện nhất?": usage(start=WEEK[0], end=WEEK[1], grain="day",
                                                    order="desc", top_n=1),
    "Tuần qua ấm đun nước dùng bao nhiêu?": typed("kettle", start=WEEK[0], end=WEEK[1]),
    "may giat hom qua": typed("washing_machine", start=YESTERDAY, end=YESTERDAY),
    "Tivi tốn điện không?": typed("television", start=YESTERDAY, end=YESTERDAY),
    "Quạt trần dùng bao nhiêu?": typed("fan"),
    "Điện hôm qua?": usage(start=YESTERDAY, end=YESTERDAY),
    "Ngày 29/10 lò vi sóng thực đo bao nhiêu?": typed("microwave", start="2026-10-29",
                                                      end="2026-10-29", source="measured"),
    "Tủ lạnh dùng bao nhiêu?": typed("fridge_freezer"),
    "Máy sấy dùng bao nhiêu?": typed("tumble_dryer"),
    "4 ngày gần đây so với 4 ngày trước?": usage(start="2026-11-01", end=YESTERDAY,
                                                compare_to="previous_period"),
    "Dùng bao nhiêu điện?": usage(),
    "Cái máy đó dùng bao nhiêu?": usage(unclear=True),
    "Tháng này tiền điện bao nhiêu?": [("compute_bill", {"day": YESTERDAY})],
    "Còn hôm qua cả nhà?": usage(start=YESTERDAY, end=YESTERDAY),
}
CHOOSE = {"Thời tiết mai thế nào?": "none"}
BILL = {"Tháng này tiền điện bao nhiêu?"}


@pytest.fixture
async def model():
    return FakeChatModel(SCRIPT, choose=CHOOSE)


def context(demo, model) -> CopilotContext:
    return CopilotContext(chat_model=model, app_sessions=demo.sessions,
                          copilot_sessions=demo.sessions, today=DEMO_TODAY,
                          text_embedder=FakeEmbedder())


@pytest.fixture
async def api(demo, model):
    async def session():
        async with demo.sessions() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_copilot_context] = lambda: context(demo, model)
    headers = {"Authorization": f"Bearer {create_access_token(str(demo.user_id))}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers=headers) as client:
        await teach(client)
        yield client
    app.dependency_overrides.clear()


async def teach(client) -> None:
    """The demo home's own phrasing for the questions below (POST /skills/{id}/examples): the
    fake embedder is too coarse to route short questions; bge-m3 routing is the eval's job."""
    skills = {s["code"]: s["id"] for s in (await client.get("/api/v1/copilot/skills")).json()}
    usage_q = [q for q in SCRIPT if q not in BILL]
    for code, examples in (("usage_query", usage_q), ("bill_explain", sorted(BILL))):
        r = await client.post(f"/api/v1/copilot/skills/{skills[code]}/examples",
                              json={"examples": examples})
        assert r.status_code == 200, r.text


async def ask(api, question: str, **extra) -> dict:
    r = await api.post("/api/v1/copilot/ask", json={"question": question, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def value(out: dict) -> float | None:
    rows = out["result"]["rows"]
    col = next(c for c in out["result"]["columns"] if c.endswith(("_kwh", "_w")))
    return rows[0][col] if rows else None


def fact(out: dict, key: str) -> str:
    return next(f["v"] for f in out["facts"] if f["k"] == key)


async def test_yesterday_whole_home(api):
    out = await ask(api, "Hôm qua nhà tôi dùng bao nhiêu điện?")
    assert out["skill"]["code"] == "usage_query" and out["retrieval"]["case"] == "choose"
    assert len(out["retrieval"]["candidates"]) == 3  # the model chose among the top n = 3
    assert value(out) == 17.25
    assert out["result"]["coverage"] == 1.0
    assert out["result"]["source"] == "measured"
    assert "$1" in out["result"]["sql"] and "2026" not in out["result"]["sql"]
    assert fact(out, "Nguồn") == "Công tơ tổng"
    assert [t["tool"] for t in out["tools"]] == ["query_usage"]
    assert {t["node"] for t in out["timings"]} >= {"find_skills", "decide", "act"}
    # the mobile app's ChatMessage, ready to append to the thread
    assert out["message"]["who"] == "ai" and out["message"]["facts"] == out["facts"]


async def test_which_day_of_last_week_used_most(api):
    out = await ask(api, "Ngày nào tuần qua dùng nhiều điện nhất?")
    assert out["result"]["rows"] == [
        {"day": "2026-10-30", "energy_kwh": 36.72, "covered_minutes": 1440.0}
    ]


async def test_kettle_last_week_falls_back_to_the_estimate(api):
    out = await ask(api, "Tuần qua ấm đun nước dùng bao nhiêu?")
    assert value(out) == 5.2
    assert out["result"]["source"] == "estimated"  # the plug covers 29 Oct only
    assert fact(out, "Nguồn") == "Ước tính NILM"


async def test_without_tone_marks(api):
    out = await ask(api, "may giat hom qua")
    assert out["result"]["rows"][0]["device"] == "Washing Machine"
    assert value(out) == 1.62 and out["result"]["source"] == "estimated"
    assert "Washing Machine" in out["retrieval"]["standalone"]  # rewrite added the name


async def test_tivi_links_to_the_television_not_the_electric_car(api, model):
    await ask(api, "Tivi tốn điện không?")
    linked = {t["ref"] for t in model.payloads[-1]["linked_terms"]}
    assert "television" in linked and "electric_car" not in linked


async def test_fan_without_data_says_so(api):
    out = await ask(api, "Quạt trần dùng bao nhiêu?")
    assert value(out) is None
    assert "Không có dữ liệu" in out["answer"] and "2026-11-04" in out["answer"]


async def test_no_device_named_means_the_whole_home(api):
    out = await ask(api, "Điện hôm qua?")
    assert value(out) == 17.25


async def test_microwave_measured_by_plug(api):
    out = await ask(api, "Ngày 29/10 lò vi sóng thực đo bao nhiêu?")
    assert value(out) == 0.06 and out["result"]["source"] == "measured"


async def test_fridge_with_no_data_in_the_period(api):
    out = await ask(api, "Tủ lạnh dùng bao nhiêu?")
    assert "Không có dữ liệu" in out["answer"]


async def test_unknown_device_is_said_and_logged_as_a_miss(api, demo):
    out = await ask(api, "Máy sấy dùng bao nhiêu?")
    assert out["result"] is None
    assert "không tìm thấy" in out["answer"]
    async with demo.sessions() as s:
        miss = await s.scalar(select(ToolCall).where(
            ToolCall.tool == "miss", ToolCall.message_id == uuid.UUID(out["message_id"])))
    assert miss is not None and miss.input["question"] == "Máy sấy dùng bao nhiêu?"


async def test_out_of_scope_runs_no_tool(api):
    out = await ask(api, "Thời tiết mai thế nào?")
    assert out["result"] is None and out["tools"] == [] and out["skill"] is None
    assert "chỉ trả lời được" in out["answer"]


async def test_compare_with_previous_period_reports_coverage(api):
    out = await ask(api, "4 ngày gần đây so với 4 ngày trước?")
    rows = {r["period"]: r["energy_kwh"] for r in out["result"]["rows"]}
    assert rows == {"current": 66.92, "previous": 77.04}
    assert fact(out, "Độ phủ (previous)") == "75%"
    assert fact(out, "kỳ trước") == "77.04 kWh"
    assert out["result"]["coverage"] == 0.75  # the weaker period, not the pooled 88%


async def test_missing_time_and_device_get_defaults_and_say_so(api):
    out = await ask(api, "Dùng bao nhiêu điện?")
    assert value(out) == 143.96
    assert fact(out, "Khoảng thời gian") == "29/10–04/11/2026"
    assert any("7 ngày" in a for a in out["assumptions"])
    assert any("cả nhà" in a for a in out["assumptions"])


async def test_unclear_question_offers_the_tracked_appliances(api):
    out = await ask(api, "Cái máy đó dùng bao nhiêu?")
    assert out["result"] is None
    labels = {o["label"] for o in out["clarification"]["options"]}
    assert labels == {"Dishwasher", "Kettle", "Microwave", "Washing Machine"}
    assert all(o["term"] is None for o in out["clarification"]["options"])  # "that" is no word


async def test_cost_uses_the_tiered_bill(api):
    out = await ask(api, "Tháng này tiền điện bao nhiêu?")
    assert out["skill"]["code"] == "bill_explain"
    assert out["cost"]["kwh"] == pytest.approx(66.92, abs=0.01)
    assert out["cost"]["amount"] > 0


async def test_follow_up_keeps_the_conversation(api):
    first = await ask(api, "Hôm qua nhà tôi dùng bao nhiêu điện?")
    second = await ask(api, "Điện hôm qua?", conversation_id=first["conversation_id"])
    assert second["conversation_id"] == first["conversation_id"]
    r = await api.get(f"/api/v1/copilot/conversations/{first['conversation_id']}/messages")
    assert [m["who"] for m in r.json()] == ["me", "ai", "me", "ai"]
    assert r.json()[1]["facts"] == first["facts"]
    threads = (await api.get("/api/v1/copilot/conversations")).json()
    assert first["conversation_id"] in {t["id"] for t in threads}


async def test_a_follow_up_is_not_hijacked_by_the_previous_unknown_device(api):
    first = await ask(api, "Máy sấy dùng bao nhiêu?")
    out = await ask(api, "Còn hôm qua cả nhà?", conversation_id=first["conversation_id"])
    assert value(out) == 17.25
    assert out["retrieval"]["rewrite"] == "rule"  # short-term memory: the last turn's call


async def test_streaming_sends_steps_then_done(api):
    async with api.stream("POST", "/api/v1/copilot/ask", json={"question": "Điện hôm qua?"},
                          headers={"Accept": "text/event-stream"}) as r:
        body = "".join([chunk async for chunk in r.aiter_text()])
    assert "event: step" in body and "event: done" in body
    assert body.index("event: step") < body.index("event: done")


async def test_without_llm_settings_ask_is_503(demo, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    async def session():
        async with demo.sessions() as s:
            yield s

    app.dependency_overrides[get_session] = session
    headers = {"Authorization": f"Bearer {create_access_token(str(demo.user_id))}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers=headers) as client:
        r = await client.post("/api/v1/copilot/ask", json={"question": "Điện hôm qua?"})
    app.dependency_overrides.clear()
    assert r.status_code == 503
