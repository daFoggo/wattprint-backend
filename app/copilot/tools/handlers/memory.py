"""The session_summary pipeline: read a finished session, summarise it, store long-term memory.

What the LLM writes (summary, topics, outcome, facts) is checked: numbers must come from the
session's tool results, fact keys from a fixed list, ids from this home, each fact quoted from a
user message. Skills, tools, actions and entities are counted from tool_call, not written by it.
"""

import datetime as dt
import json
import re
import uuid
from datetime import UTC
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from ....models import HomeMemory, Message, SessionSummary, ToolCall
from ...agents import llm
from ...skills.grounding import numbers, ungrounded
from ...utils.helpers import detect_lang
from ..registry import RunContext, handler

FACT_KEYS = {  # key -> the value fields it must carry
    "preference.lang": {"lang"}, "preference.detail_level": {"level"},
    "interest.device": {"device_id"}, "interest.topic": {"topic"},
    "commitment.alert": {"alert_id"}, "commitment.suggestion": {"suggestion_id"},
    "fact.occupancy": {"occupants"},
}
_PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|(?<!\d)(?:\+?84|0)\d{8,10}(?!\d)")


class MemoryFact(BaseModel):
    key: str = Field(description="one of: " + ", ".join(FACT_KEYS))
    value: dict[str, Any]
    quote: str = Field(description="the user's words this fact comes from, copied exactly")


class SessionSummaryOut(BaseModel):
    summary: str = Field(max_length=600, description="what the user wanted and got, in the "
                         "session's language; numbers only as they appear in the tool results")
    topics: list[str] = Field(default=[], max_length=5, description="short labels")
    outcome: Literal["resolved", "partly", "unresolved"]
    open_items: list[str] = Field(default=[], description="what stayed unanswered")
    facts: list[MemoryFact] = []


@handler("read_session")
async def read_session(args, rc: RunContext) -> dict:
    conv = uuid.UUID(rc.conversation_id)
    async with rc.ctx.app()() as s:
        since = await s.scalar(select(SessionSummary.covers_until)
                               .where(SessionSummary.conversation_id == conv))
        q = select(Message).where(Message.conversation_id == conv,
                                  Message.role.in_(("user", "assistant")))
        msgs = (await s.execute(q.order_by(Message.created_at))).scalars().all()
        calls = (await s.execute(select(ToolCall).where(
            ToolCall.message_id.in_([m.id for m in msgs])).order_by(ToolCall.created_at))
        ).scalars().all()
    if not msgs or (since and msgs[-1].created_at <= since):
        return {"data": {"empty": True}, "no_data": True}
    skills, tools, actions, devices, periods, open_items = [], {}, [], set(), [], []
    for c in calls:
        if c.tool == "skill_search":
            code = (c.input or {}).get("chosen")
            if code and code not in skills:
                skills.append(code)
            continue
        if c.tool == "miss":
            continue
        t = tools.setdefault(c.tool, {"tool": c.tool, "calls": 0, "ok": 0})
        t["calls"] += 1
        t["ok"] += bool(c.ok)
        args_ = (c.input or {}).get("args", {})
        devices.update(args_.get("device_ids") or [])
        goal = (c.input or {}).get("goal")
        if goal:
            periods.append([goal["start"], goal["end"]])
        out = (c.input or {}).get("data") or {}
        if c.tool == "create_alert" and c.ok and out.get("alert_id"):
            actions.append({"tool": "create_alert", "ref": out["alert_id"]})
        if c.ok is None:
            open_items.append(f"pending confirmation: {c.tool}")
        elif c.ok is False:
            open_items.append(f"failed: {c.tool}")
    sources = [json.dumps(c.input, ensure_ascii=False, default=str) for c in calls]
    return {"data": {
        "messages": [{"role": m.role, "content": m.content[:800]} for m in msgs[-20:]],
        "turns": sum(m.role == "user" for m in msgs),
        "started_at": msgs[0].created_at.isoformat(), "ended_at": msgs[-1].created_at.isoformat(),
        "skills_used": skills, "tools_used": list(tools.values()), "actions": actions,
        "entities": {"devices": sorted(devices), "periods": periods},
        "open_items": open_items, "sources": sources,
        "user_text": " \n".join(m.content for m in msgs if m.role == "user"),
        "user_messages": [m.content for m in msgs if m.role == "user"],
    }}


def _checked_facts(facts: list[MemoryFact], session: dict, home: dict) -> list[MemoryFact]:
    ok = []
    for f in facts:
        if f.key not in FACT_KEYS or not FACT_KEYS[f.key] <= set(f.value):
            continue
        if not f.quote.strip() or f.quote.strip().lower() not in session["user_text"].lower():
            continue
        if f.key == "interest.device" and f.value["device_id"] not in home.get("devices", {}):
            continue
        if f.key == "commitment.alert" and str(f.value["alert_id"]) not in home["alert_ids"]:
            continue  # an id the LLM made up, or a description in place of one
        if (f.key == "commitment.suggestion"
                and str(f.value["suggestion_id"]) not in home["suggestion_ids"]):
            continue
        if f.key == "preference.lang" and f.value["lang"] not in ("vi", "en"):
            continue
        ok.append(f)
    return ok


def _clean_summary(summary: str, sources: list[str]) -> str:
    summary = _PII.sub("…", summary)
    for token in ungrounded(summary, sources):
        summary = summary.replace(token, "…")
    return summary[:600]


@handler("summarize_session")
async def summarize_session(args, rc: RunContext) -> dict:
    session = rc.results.get("read_session") or {}
    if session.get("empty"):
        return {"data": {"skipped": True}, "no_data": True}
    model = rc.ctx.optional_model()
    if model is None:
        return {"ok": False, "error": "no chat model: the session is not summarised"}
    out = await llm.structured(model, SessionSummaryOut, llm.SUMMARIZE, dict(
        messages=session["messages"], skills_used=session["skills_used"],
        tools_used=session["tools_used"], open_items=session["open_items"]))
    sources = [*session["sources"], *(m["content"] for m in session["messages"])]
    # the language is detected, not asked: the LLM confuses it with the language it answered in
    async with rc.ctx.app()() as s:
        home_id = uuid.UUID(rc.home["id"])
        ids = {name: {str(i) for i in (await s.execute(text(
            f"SELECT id FROM {table} WHERE home_id = :h"), {"h": home_id})).scalars()}
            for name, table in (("alert_ids", "insight.alert"),
                                ("suggestion_ids", "copilot.suggestion"))}
    facts = [f for f in _checked_facts(out.facts, session, {**rc.home, **ids})
             if f.key != "preference.lang"]
    langs = {detect_lang(m) for m in session["user_messages"]}
    if len(session["user_messages"]) >= 2 and len(langs) == 1:
        facts.append(MemoryFact(key="preference.lang", value={"lang": langs.pop()},
                                quote=session["user_messages"][0]))
    return {"data": {"summary": _clean_summary(out.summary, sources),
                     "topics": [t[:40] for t in out.topics[:5]], "outcome": out.outcome,
                     "open_items": [*session["open_items"], *out.open_items][:10],
                     "facts": [f.model_dump() for f in facts],
                     "dropped_numbers": [t for t in numbers(out.summary)
                                         if t in ungrounded(out.summary, sources)]}}


@handler("store_session_memory", side_effect="write")
async def store_session_memory(args, rc: RunContext) -> dict:
    session, made = rc.results.get("read_session") or {}, rc.results.get("summarize_session") or {}
    if not made or made.get("skipped"):
        return {"data": {"stored": False}, "no_data": True}
    vector = (await rc.ctx.embedder().embed(
        [f"{made['summary']} {' '.join(made['topics'])}"]))[0]
    conv, home = uuid.UUID(rc.conversation_id), uuid.UUID(rc.home["id"])
    row = dict(home_id=home, user_id=uuid.UUID(rc.user["id"]),
               started_at=dt.datetime.fromisoformat(session["started_at"]),
               ended_at=dt.datetime.fromisoformat(session["ended_at"]),
               turns=session["turns"], summary=made["summary"], topics=made["topics"],
               skills_used=session["skills_used"], tools_used=session["tools_used"],
               actions=session["actions"], entities=session["entities"],
               open_items=made["open_items"], outcome=made["outcome"], embedding=vector,
               covers_until=dt.datetime.fromisoformat(session["ended_at"]),
               model=getattr(rc.ctx.optional_model(), "model_name", "") or "")
    async with rc.ctx.app()() as s:
        stmt = insert(SessionSummary).values(conversation_id=conv, **row)
        await s.execute(stmt.on_conflict_do_update(
            index_elements=[SessionSummary.conversation_id],
            set_={**{k: stmt.excluded[k] for k in row}, "updated_at": text("now()")}))
        for f in made["facts"]:
            user = None if f["key"].startswith("fact.") else uuid.UUID(rc.user["id"])
            stmt = insert(HomeMemory).values(home_id=home, user_id=user,
                                             kind=f["key"].split(".")[0], key=f["key"],
                                             value=f["value"], evidence=[conv])
            await s.execute(stmt.on_conflict_do_update(
                constraint="uq_home_memory_home_id",
                set_={"confidence": text("least(copilot.home_memory.confidence + 0.1, 1)"),
                      "last_seen_at": dt.datetime.now(UTC),
                      "evidence": text("array(SELECT DISTINCT unnest(copilot.home_memory.evidence"
                                       " || excluded.evidence))")}))
        await s.commit()
    return {"data": {"stored": True, "facts": len(made["facts"])}}
