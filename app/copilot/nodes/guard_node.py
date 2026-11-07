"""guard_output: the LLM's reply may only say what the tool results say (spec 5.2). No LLM.

Every number must appear in the facts or results; no ids, SQL or JSON; no claim of a change
that did not happen. Otherwise the reply becomes the facts read out.
"""

import json
import re

from langgraph.runtime import Runtime

from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState
from ..skills.grounding import ungrounded
from .answer_node import facts_text

MAX_CHARS = 1200
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_SQL = re.compile(r"\bselect\b.+\bfrom\b|\bcopilot_ro\.", re.I | re.S)
_CLAIM = re.compile(r"đã tạo|đã lưu|đã cài|đã bật|i (have )?(created|set up|saved)", re.I)


async def guard_output(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    answer = state.get("answer") or ""
    if state.get("answer_source") != "llm" or not answer:
        return {}
    results = state.get("results", [])
    sources = [json.dumps([r.get("data") for r in results], ensure_ascii=False, default=str),
               facts_text(state), state.get("question") or "", state.get("standalone") or "",
               str(runtime.context.local_today()), state["home"].get("latest_date") or ""]
    flags = []
    if bad := ungrounded(answer, sources):
        flags.append(f"ungrounded:{','.join(bad[:5])}")
    if _UUID.search(answer) or _SQL.search(answer) or answer.lstrip().startswith(("{", "[")):
        flags.append("leak")
    wrote = any(r.get("ok") and r["tool"] in ("create_alert",) for r in results)
    if _CLAIM.search(answer) and not wrote:
        flags.append("false_claim")
    if not flags:
        return {"answer": answer[:MAX_CHARS]}
    return {"answer": facts_text(state) or answer[:MAX_CHARS], "answer_source": "template",
            "flags": flags}
