"""decide: choose the skill, then the tool calls (spec 5.2).

Skill: given (schedule, event, confirm), else one LLM choice among the top-n candidates the
search ranked. Tools: a pipeline runs its tools in order with no LLM; an agent skill
gets one tool-calling round (native function calling, the skill's tools only, presets hidden).
"""

import datetime as dt
import json
import logging
import uuid
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.runtime import Runtime
from pydantic import BaseModel
from sqlalchemy import text

from ..agents import llm
from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState
from ..skills import retrieval
from ..skills.chunker import no_tone
from ..tools.registry import FORBIDDEN_ARGS, locked

log = logging.getLogger(__name__)


class SkillChoice(BaseModel):
    code: str
    reason: str = ""


def tool_spec(tool: dict) -> dict:
    """OpenAI function definition with the preset arguments removed."""
    schema = json.loads(json.dumps(tool["parameters"]))
    for name in locked(tool["preset"]):
        schema.get("properties", {}).pop(name, None)
        if name in schema.get("required", []):
            schema["required"].remove(name)
    return {"type": "function", "function": {"name": tool["name"],
                                             "description": tool["description"],
                                             "parameters": schema}}


def _terms(state: TurnState) -> list[dict]:
    return [{"source": c.source, "kind": c.kind, "ref": c.ref, "phrase": c.phrase,
             "devices": [{"id": i, "name": n} for i, n in zip(c.device_ids, c.device_names,
                                                              strict=False)],
             "from_previous_question": c.from_history} for c in state.get("terms", [])]


def _payload(state: TurnState, today: dt.date) -> dict:
    day = dt.timedelta(days=1)
    return {
        "question": state.get("standalone") or state["question"],
        "original": state.get("question"), "language": state["lang"],
        "today": str(today),
        "dates": {"yesterday": str(today - day),
                  "last_7_days": [str(today - 7 * day), str(today - day)],
                  "this_month": [str(today.replace(day=1)), str(today - day)]},
        "resolved_dates": state.get("dates"),
        "latest_data_date": state["home"].get("latest_date"),
        "tracked_devices": state["home"].get("tracked", []),
        "linked_terms": _terms(state),
        "devices_of_the_previous_turn": state.get("rewrite", {}).get("carried", []),
        "history": state.get("history", []),
        "memory": [{"summary": m["summary"], "ended_at": m["ended_at"]}
                   for m in state.get("memory", {}).get("sessions", [])],
        "household_facts": state.get("memory", {}).get("facts", []),
    }


async def _examples(ctx: CopilotContext, home_id: str, candidates: list[dict]) -> dict:
    """Two example questions per candidate skill, the home's own first, as written (with tones)."""
    ids = [c["id"] for c in candidates if c.get("id")]
    if not ids:
        return {}
    async with ctx.app()() as s:
        rows = await s.execute(text(
            "SELECT skill_id::text AS id, text FROM copilot.catalog_chunk WHERE kind = 'example' "
            "AND skill_id = ANY(CAST(:ids AS uuid[])) AND (home_id IS NULL OR home_id = "
            "CAST(:home AS uuid)) ORDER BY home_id NULLS LAST, ord"), {"ids": ids, "home": home_id})
        out: dict[str, list[str]] = {}
        for r in rows:
            if r.text != no_tone(r.text) and len(out.setdefault(r.id, [])) < 2:
                out[r.id].append(r.text)
    return out


async def _choose(state: TurnState, ctx: CopilotContext) -> str | None:
    """The model picks one of the top-n skills the search ranked (or none)."""
    examples = await _examples(ctx, state["home"]["id"], state["candidates"])
    payload = {"question": state.get("standalone") or state["question"],
               "history": state.get("history", [])[-2:],
               "candidates": [{"code": c["code"], "name": c["name"],
                               "description": c["description"],
                               "examples": examples.get(c.get("id"), []),
                               "household": c.get("own", False)}
                              for c in state["candidates"]]}
    try:
        choice = await llm.structured(ctx.model(), SkillChoice, llm.SKILL_CHOICE, payload)
    except Exception as exc:
        log.warning("skill choice failed: %s", exc)
        choice = None
    codes = {c["code"] for c in state["candidates"]}
    if choice is not None and choice.code in codes:
        return choice.code
    # "none" is wrong for a follow-up completed from the last turn and for a question that
    # names one of the home's devices: both are in scope
    if (state.get("rewrite") or {}).get("carried") or any(
            t.device_ids and not t.from_history for t in state.get("terms", [])):
        return state["candidates"][0]["code"]
    return None


def _messages(state: TurnState, skill: dict, today: dt.date) -> list:
    system = (f"{llm.AGENT}\n\nSkill: {skill['name']} — {skill['description']}\n"
              f"Skill instructions: {skill['instructions'] or '(none)'}")
    msgs = [SystemMessage(system),
            HumanMessage(json.dumps(_payload(state, today), ensure_ascii=False, default=str))]
    for r in state.get("transcript", []):
        msgs.append(AIMessage(content="", tool_calls=[
            {"name": c["tool"], "args": c["args"], "id": c["id"]} for c in r["calls"]]))
        msgs += [ToolMessage(content=r["results"].get(c["id"], "{}"), tool_call_id=c["id"])
                 for c in r["calls"]]
    return msgs


async def decide(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    ctx, out = runtime.context, {}
    skill = state.get("skill")
    if skill is None:
        code = await _choose(state, ctx)
        if code is None:
            return {"outcome": "other", "plan": []}
        async with ctx.app()() as s:
            skill = await retrieval.load_skill(s, home_id=state["home"]["id"], code=code)
        if skill is None:
            return {"outcome": "other", "plan": []}
        out["skill"] = skill
    if skill["mode"] == "pipeline":
        return {**out, "plan": [{"id": str(uuid.uuid4()), "tool": t["name"], "args": {},
                                 "source": "pipeline"} for t in skill["tools"]]}
    if "injection" in state.get("flags", []):
        return {**out, "outcome": "refused", "plan": []}
    tools = {t["name"]: t for t in skill["tools"]}
    model = ctx.model().bind_tools([tool_spec(t) for t in skill["tools"]])
    reply = await model.ainvoke(_messages(state, skill, ctx.local_today()))
    done = {(r["tool"], json.dumps(r["args"], sort_keys=True, default=str))
            for r in state.get("results", []) if r.get("ok")}
    plan, rejected = [], {}
    for call in getattr(reply, "tool_calls", None) or []:
        cid = call.get("id") or str(uuid.uuid4())
        args = call.get("args") or {}
        if call["name"] not in tools:
            rejected[cid] = (call, f"{call['name']} is not a tool of this skill")
        elif set(args) & FORBIDDEN_ARGS:
            rejected[cid] = (call, f"arguments not allowed: {sorted(set(args) & FORBIDDEN_ARGS)}")
        elif (call["name"], json.dumps(args, sort_keys=True, default=str)) in done:
            continue  # the same call already ran this turn
        else:
            plan.append({"id": cid, "tool": call["name"], "args": args, "source": "llm"})
    if rejected:  # the LLM sees why on its next round
        out["transcript"] = [*state.get("transcript", []), {
            "calls": [{"id": i, "tool": c["name"], "args": c.get("args") or {}}
                      for i, (c, _) in rejected.items()],
            "results": {i: json.dumps({"error": e}) for i, (_, e) in rejected.items()}}]
        out["failed_rounds"] = state.get("failed_rounds", 0) + 1
    if not plan and not state.get("results"):
        out["outcome"] = "no_tool"
    return {**out, "plan": plan, "rounds": state.get("rounds", 0) + 1}


def route_after_decide(state: TurnState) -> Literal["act", "generate_answer"]:
    return "act" if state.get("plan") else "generate_answer"
