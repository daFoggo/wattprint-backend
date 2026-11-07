"""rewrite_question: link the words, resolve dates, make a follow-up standalone (spec 5.2).

Rules first: the lexicon links devices and household words, fixed anchors resolve "hôm qua"
and "29/10", and a follow-up takes the appliance of the last turn (short-term memory). The LLM
rewrites only a follow-up the rules cannot complete, and may not add numbers.
"""

import datetime as dt
import re

from langgraph.runtime import Runtime
from pydantic import BaseModel

from ..agents import llm
from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState
from ..memory import lexicon
from ..skills.chunker import no_tone
from ..skills.grounding import ungrounded
from ..skills.query_planning import period_text
from ..tools import db_connector as db

FOLLOWUP = re.compile(r"^\s*(con|the con|vay con|con ve|and|what about|how about)\b")


class Rewrite(BaseModel):
    question: str


def resolve_dates(text: str, today: dt.date) -> dict[str, str] | None:
    t, day = no_tone(text), dt.timedelta(days=1)
    month_start = today.replace(day=1)
    if "hom kia" in t or "day before yesterday" in t:
        a = b = today - 2 * day
    elif "hom qua" in t or "yesterday" in t:
        a = b = today - day
    elif "hom nay" in t or "today" in t:
        a = b = today
    elif any(w in t for w in ("tuan qua", "tuan nay", "7 ngay", "last week", "this week")):
        a, b = today - 7 * day, today - day
    elif "thang nay" in t or "this month" in t or "ky nay" in t:
        a, b = month_start, today - day
    elif "thang truoc" in t or "last month" in t:
        b = month_start - day
        a = b.replace(day=1)
    elif m := re.search(r"\b(\d{1,2})/(\d{1,2})\b", t):
        try:
            a = b = dt.date(today.year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    else:
        return None
    return {"start": str(a), "end": str(b)}


def _last_devices(last: dict | None) -> list[str]:
    for call in reversed((last or {}).get("calls", [])):
        if call["tool"] == "query_usage" and call.get("ok"):
            return call["args"].get("device_ids") or call["args"].get("device_type_codes") or []
    return []


async def rewrite_question(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    ctx, q = runtime.context, state["question"]
    history = state.get("history", [])
    previous = [m["content"] for m in history if m["role"] == "user"][-1:]
    found: dict[tuple, object] = {}
    async with db.copilot_tx(ctx.copilot(), state["token"]) as conn:
        for i, text in enumerate([q, *previous]):
            for c in await lexicon.link_entities(conn, text):
                found.setdefault((c.source, c.kind, c.ref),
                                 c.model_copy(update={"from_history": i > 0}))
    terms = list(found.values())
    own = [c for c in terms if not c.from_history]
    dates = resolve_dates(q, ctx.local_today())
    carried = _last_devices(state.get("last_turn"))
    followup = bool(FOLLOWUP.match(no_tone(q))) or (len(q.split()) <= 4 and not own and carried)
    method, standalone = "none", q
    if followup and previous and carried:
        method, standalone = "rule", f"{q} — {previous[0]}"
    elif followup and previous and ctx.optional_model() is not None:
        try:
            out = await llm.structured(ctx.model(), Rewrite, llm.REWRITE,
                                       {"follow_up": q, "history": history[-4:]})
            if not ungrounded(out.question, [q, *(m["content"] for m in history)]):
                method, standalone = "llm", out.question
        except Exception:
            pass  # keep the raw question
    names = sorted({n for c in own for n in c.device_names})
    tail = "; ".join(filter(None, [", ".join(names),
                                   period_text(dt.date.fromisoformat(dates["start"]),
                                               dt.date.fromisoformat(dates["end"]))
                                   if dates else ""]))
    if tail:
        standalone = f"{standalone} [{tail}]"
        method = "rule" if method == "none" else method
    return {"terms": terms, "dates": dates, "standalone": standalone,
            "rewrite": {"method": method, "carried": carried if method == "rule" else []}}
