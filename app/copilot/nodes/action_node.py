"""act: run the planned tool calls (spec 5.2). No LLM (except inside phrase/summarize tools).

Every call: presets over the LLM's arguments → the handler's pydantic validation → the handler
with its timeout. A write the LLM asked for stops with a confirmation card; pipeline writes and
confirmed calls run. Agent reads of one round run in parallel; pipelines in order, each tool
seeing the earlier outputs. Every call becomes a tool_call row.
"""

import asyncio
import json
import time
import uuid
from typing import Literal

from langgraph.runtime import Runtime
from pydantic import ValidationError

from ..agents.base_agent import CopilotContext
from ..agents.state import Fact, TurnState
from ..config.settings import LLM
from ..tools.registry import RunContext, handlers, locked


def _summary(out: dict) -> str:
    """What the LLM sees of a result: data or the error, never SQL."""
    if out.get("ok") is False:
        return json.dumps({"error": out.get("error")}, ensure_ascii=False)
    return json.dumps(out.get("data") or {}, ensure_ascii=False, default=str)[:6000]


async def _run(call: dict, tool: dict, rc: RunContext) -> dict:
    h = handlers()[tool["handler"]]
    try:
        hidden = locked(tool["preset"])
        args = h.args.model_validate({**{k: v for k, v in call["args"].items() if k not in hidden},
                                      **tool["preset"]})
    except ValidationError as exc:
        return {"ok": False, "error": f"invalid arguments: {exc.errors(include_url=False)}"[:600],
                "ms": 0}
    if h.side_effect == "write" and call["source"] == "llm":
        return {"ok": None, "pending": True, "args": args.model_dump(mode="json"), "ms": 0}
    t0 = time.perf_counter()
    try:
        out = await asyncio.wait_for(h.fn(args, rc), tool["timeout_ms"] / 1000)
    except TimeoutError:
        out = {"ok": False, "error": f"{tool['name']} timed out"}
    except Exception as exc:  # a failed tool is a result the LLM (or the answer) handles
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
    return {"ok": True, **out, "args": args.model_dump(mode="json"),
            "ms": out.get("ms") or round((time.perf_counter() - t0) * 1000)}


async def act(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    skill, plan = state["skill"], state["plan"]
    tools = {t["name"]: t for t in skill["tools"]}
    rc = RunContext(ctx=runtime.context, home=state["home"], token=state["token"],
                    lang=state.get("lang", "vi"), user=state.get("user"),
                    terms=state.get("terms", []),
                    question=state.get("standalone") or state.get("question") or "",
                    conversation_id=state.get("conversation_id"),
                    results=dict(state.get("tool_data") or {}))
    if skill["mode"] == "pipeline":
        outs = []
        for call in plan:
            out = await _run(call, tools[call["tool"]], rc)
            rc.results[call["tool"]] = out.get("data") or {}
            outs.append(out)
            if out.get("ok") is False:
                break  # the later steps need this one's output
    else:
        reads = [c for c in plan if handlers()[tools[c["tool"]]["handler"]].side_effect == "read"]
        writes = [c for c in plan if c not in reads]
        outs_by_id = dict(zip([c["id"] for c in reads], await asyncio.gather(
            *(_run(c, tools[c["tool"]], rc) for c in reads)), strict=True))
        for c in writes:
            outs_by_id[c["id"]] = await _run(c, tools[c["tool"]], rc)
            rc.results[c["tool"]] = outs_by_id[c["id"]].get("data") or {}
        for c in reads:
            rc.results[c["tool"]] = outs_by_id[c["id"]].get("data") or {}
        outs = [outs_by_id[c["id"]] for c in plan]

    results, queries, facts, api, card = [], [], [], dict(state.get("api") or {}), None
    for call, out in zip(plan, outs, strict=False):
        tool = tools[call["tool"]]
        row_id = str(uuid.uuid4())
        if out.get("pending"):
            card = {"kind": "confirm", "call_id": row_id, "tool": tool["name"],
                    "label": tool["label_vi"] if rc.lang == "vi" else tool["label_en"],
                    "args": out["args"]}
            queries.append({"id": row_id, "tool": tool["name"], "ok": None,
                            "input": {"args": out["args"], "skill": skill["code"]}})
            results.append({"id": call["id"], "tool": tool["name"], "args": out["args"],
                            "ok": None, "pending": True, "ms": 0})
            continue
        item_facts = [f if isinstance(f, Fact) else Fact(**f) for f in out.get("facts", [])]
        facts += item_facts
        api.update(out.get("api") or {})
        if out.get("card") and card is None:
            card = {"kind": "clarification", **out["card"]}
        row = {"tool": tool["name"], "ok": out["ok"], "sql": out.get("sql"),
               "unit": out.get("unit"), "duration_ms": out["ms"],
               "input": {"args": out.get("args", call["args"]), "skill": skill["code"],
                         "data": out.get("data"), "error": out.get("error"),
                         "goal": out.get("goal"),
                         "facts": [f.model_dump() for f in item_facts]}}
        if call["source"] == "confirm":
            row["update_id"] = call["id"]
        else:
            row["id"] = row_id
        queries.append(row)
        if out.get("miss"):
            queries.append({"tool": "miss", "ok": False, "input": {
                "question": state.get("question"),
                "error": out.get("error") or out.get("no_device"),
                "unmatched": out.get("args", {}).get("unmatched", [])}})
        results.append({"id": call["id"], "tool": tool["name"], "args": out.get("args", {}),
                        "ok": out["ok"], "error": out.get("error"), "data": out.get("data"),
                        "no_data": bool(out.get("no_data")), "no_device": out.get("no_device"),
                        "assumptions": out.get("assumptions", []), "ms": out["ms"]})
    failed = any(r["ok"] is False for r in results)
    update = {"results": results, "queries": queries, "facts": facts, "api": api,
              "tool_data": rc.results, "plan": [],
              "failed_rounds": state.get("failed_rounds", 0) + failed}
    if card is not None:
        update["card"] = card
    if skill["mode"] == "agent":
        update["transcript"] = [*state.get("transcript", []), {
            "calls": [{"id": c["id"], "tool": c["tool"], "args": c["args"]} for c in plan],
            "results": {c["id"]: _summary(o) for c, o in zip(plan, outs, strict=False)}}]
    return update


def route_after_act(state: TurnState) -> Literal["decide", "generate_answer"]:
    """Back to the LLM only to fix a failed call, within the step limits."""
    skill = state["skill"]
    last = state.get("transcript", [])[-1:] or [{}]
    failed_now = any('"error"' in v for v in last[0].get("results", {}).values())
    if (skill["mode"] == "agent" and failed_now and not state.get("card")
            and state.get("rounds", 0) < skill["max_steps"]
            and state.get("failed_rounds", 0) < LLM["executor"]["max_failed_rounds"]):
        return "decide"
    return "generate_answer"
