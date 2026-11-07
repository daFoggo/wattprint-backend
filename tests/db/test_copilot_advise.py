"""Seam 2: the advice run's entry point on the demo home (no LLM: template text), plus the
feedback, rules and refresh endpoints. "Today" is 5 Nov 2026; the dump covers 29 Oct .. 4 Nov.
"""

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.cli.copilot_run import run_skill
from app.config import settings
from app.copilot.agents.base_agent import CopilotContext
from app.database import get_session
from app.main import app
from app.models import SavingsMeasure, Suggestion
from app.routers.copilot import get_copilot_context
from app.security import create_access_token
from tests.db.conftest import DEMO_TODAY, FakeChatModel, FakeEmbedder


@pytest.fixture
async def clean(demo):
    """Every test starts with no advice, feedback, motif instances or household rules."""
    async with demo.sessions() as s:
        for table in ("copilot.savings_measure", "copilot.suggestion_feedback",
                      "copilot.suggestion", "insight.motif_instance"):
            await s.execute(text(f"DELETE FROM {table}"))
        await s.execute(text("DELETE FROM copilot.rule WHERE home_id IS NOT NULL"))
        await s.commit()


def context(demo, today=DEMO_TODAY, model=False) -> CopilotContext:
    return CopilotContext(chat_model=model, app_sessions=demo.sessions,
                          copilot_sessions=demo.sessions, today=today,
                          text_embedder=FakeEmbedder())


async def run_home(home_id, today, ctx) -> dict:
    """The daily_advice skill's pipeline (schedule trigger); returns the stored ids as before."""
    ctx.today = today
    state = await run_skill(home_id, "daily_advice", ctx)
    data = state.get("tool_data") or {}
    return {**state, "stored": (data.get("store_suggestions") or {}).get("stored", []),
            "measured": (data.get("measure_savings") or {}).get("measured", [])}


async def stored(demo) -> list[Suggestion]:
    async with demo.sessions() as s:
        return list((await s.execute(
            select(Suggestion).where(Suggestion.status.in_(("proposed", "shown")))
            .order_by(Suggestion.expected_amount.desc())
        )).scalars())


@pytest.fixture
async def client(demo):
    model = FakeChatModel({"Làm sao để tiết kiệm điện?": [("read_suggestions", {})]})

    async def session():
        async with demo.sessions() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_copilot_context] = lambda: context(demo, model=model)

    def as_user(user_id: uuid.UUID) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {create_access_token(str(user_id))}"})

    yield as_user
    app.dependency_overrides.clear()


async def test_advice_run_finds_the_demo_patterns(demo, clean):
    state = await run_home(demo.home_id, DEMO_TODAY, context(demo))
    assert len(state["stored"]) == 3
    advice = {g.kind: g for g in await stored(demo)}
    assert set(advice) == {"tier_alert", "high_day_review", "standby_hunt"}
    night = advice["standby_hunt"].evidence
    assert (night["night"], night["min_w"], night["median_w"]) == ("2026-10-30", 2729, 327)
    days = advice["high_day_review"].evidence
    assert days["instances"] == 2 and days["day"] == "2026-10-30"  # 29 and 30 Oct fired
    assert advice["tier_alert"].evidence["tier"] == 4
    assert "bậc 4" in advice["tier_alert"].body
    for g in advice.values():  # priced, linked to the rule and the triggering instance
        assert g.expected_amount > 0 and g.rule_id and g.motif_instance_id


async def test_a_second_run_does_not_repeat_open_advice(demo, clean):
    await run_home(demo.home_id, DEMO_TODAY, context(demo))
    again = await run_home(demo.home_id, DEMO_TODAY, context(demo))
    assert again["stored"] == []


async def test_rejected_twice_stops_coming_back_and_snooze_waits(demo, clean, client):
    async with client(demo.user_id) as api:
        await run_home(demo.home_id, DEMO_TODAY, context(demo))
        for round_ in (1, 2):
            night = next(g for g in await stored(demo) if g.kind == "standby_hunt")
            r = await api.post(f"/api/v1/copilot/suggestions/{night.id}/feedback",
                               json={"action": "reject"})
            assert r.status_code == 200 and r.json()["status"] == "dismissed"
            await run_home(demo.home_id, DEMO_TODAY, context(demo))
            kinds = {g.kind for g in await stored(demo)}
            assert ("standby_hunt" in kinds) == (round_ == 1)  # once: back; twice: gone
        tier = next(g for g in await stored(demo) if g.kind == "tier_alert")
        await api.post(f"/api/v1/copilot/suggestions/{tier.id}/feedback",
                       json={"action": "snooze"})
        await run_home(demo.home_id, DEMO_TODAY, context(demo))
        assert "tier_alert" not in {g.kind for g in await stored(demo)}


async def test_accepted_advice_gets_a_measured_saving_a_week_later(demo, clean, client):
    await run_home(demo.home_id, DEMO_TODAY, context(demo))
    day = next(g for g in await stored(demo) if g.kind == "high_day_review")
    async with client(demo.user_id) as api:
        r = await api.post(f"/api/v1/copilot/suggestions/{day.id}/feedback",
                           json={"action": "accept"})
    assert r.json()["status"] == "accepted"
    accepted_on = dt.datetime.now(dt.UTC).date()
    await run_home(demo.home_id, accepted_on + dt.timedelta(days=6), context(demo))
    async with demo.sessions() as s:
        assert await s.get(SavingsMeasure, day.id) is None  # not a week yet
    await run_home(demo.home_id, accepted_on + dt.timedelta(days=8), context(demo))
    async with demo.sessions() as s:
        measure = await s.get(SavingsMeasure, day.id)
    assert measure is not None and "7 local days" in measure.method
    async with client(demo.user_id) as api:
        shown = (await api.get("/api/v1/copilot/suggestions", params={"status": "all"})).json()
    saving = next(g for g in shown if g["id"] == str(day.id))["measured_saving"]
    assert saving["baseline_kwh"] == float(measure.baseline_kwh)


async def test_rules_owner_writes_and_dry_run(demo, clean, client):
    await run_home(demo.home_id, DEMO_TODAY, context(demo))  # detects the instances
    body = {"motif": "night_baseline", "window_days": 7,
            "when": {"quantifier": "at_least_one",
                     "where": {"fact": "min_w", "op": ">", "value": 300, "unit": "W"}},
            "then": {"suggest": "standby_hunt", "per": "home"}}
    async with client(demo.user_id) as api:
        r = await api.post("/api/v1/copilot/rules", json={"name": "Đêm > 300 W", "body": body})
        assert r.status_code == 201, r.text
        # nights of 29 Oct .. 4 Nov: 121, 2729, 103, 327, 402, 388, 248 W -> 4 above 300 W
        assert r.json()["dry_run_hits"] == 4
        three = {**body, "when": {**body["when"], "quantifier": "at_least", "n": 3}}
        r = await api.post("/api/v1/copilot/rules", json={"name": "3 đêm > 300 W", "body": three})
        assert r.json()["dry_run_hits"] == 4  # the spec's "at least 3 nights" fires
        five = {**body, "when": {**body["when"], "quantifier": "at_least", "n": 5}}
        r = await api.post("/api/v1/copilot/rules", json={"name": "5 đêm > 300 W", "body": five})
        assert r.json()["dry_run_hits"] == 0
        bad = {**body, "motif": "laundry_party"}
        r = await api.post("/api/v1/copilot/rules", json={"name": "x", "body": bad})
        assert r.status_code == 422 and "laundry_party" in r.text
        mismatch = {**body, "then": {"suggest": "long_run_check", "per": "home"}}
        r = await api.post("/api/v1/copilot/rules", json={"name": "y", "body": mismatch})
        assert r.status_code == 422 and "long_run" in r.text  # its text needs run facts
        shared = (await api.get("/api/v1/copilot/rules")).json()
        assert sum(1 for x in shared if x["shared"]) == 5


async def test_a_member_cannot_write_rules(demo, client):
    member = uuid.uuid4()
    async with demo.sessions() as s:
        await s.execute(text("INSERT INTO users (id, email, full_name) VALUES (:u, :e, 'Em')"),
                        {"u": member, "e": f"{member.hex[:8]}@example.com"})
        await s.execute(text("INSERT INTO core.home_member (home_id, user_id, role) "
                             "VALUES (:h, :u, 'member')"), {"h": demo.home_id, "u": member})
        await s.commit()
    body = {"motif": "night_baseline", "when": {"quantifier": "at_least_one"},
            "then": {"suggest": "standby_hunt"}}
    async with client(member) as api:
        r = await api.post("/api/v1/copilot/rules", json={"name": "m", "body": body})
    assert r.status_code == 403


async def test_refresh_and_asking_for_advice_in_the_chat(demo, clean, client):
    async with client(demo.user_id) as api:
        r = await api.post("/api/v1/copilot/suggestions/refresh")
        assert r.status_code == 200 and r.json()["stored"] == 3
        r = await api.post("/api/v1/copilot/ask", json={"question": "Làm sao để tiết kiệm điện?"})
        out = r.json()
    assert len(out["suggestions"]) == 3
    top = max(out["suggestions"], key=lambda g: g["expected_amount"])
    assert out["message"]["cta"] == top["title"] and out["message"]["ctaDesc"] == top["body"]
    assert len(out["facts"]) == 3


async def test_without_an_openrouter_key_the_run_still_uses_templates(demo, clean, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    state = await run_home(demo.home_id, DEMO_TODAY, context(demo, model=None))
    assert len(state["stored"]) == 3
