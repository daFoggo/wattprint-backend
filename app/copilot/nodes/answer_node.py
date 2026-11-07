"""generate_answer and suggest_followups (spec 5.2): the reply from the tool results.

Templates for cards, out-of-scope, no data and failures; the LLM words the rest from the results
(numbers only from them). Schedule and event runs have no reply.
"""

import datetime as dt
import json
import logging
from zoneinfo import ZoneInfo

from langgraph.runtime import Runtime

from ..agents import llm
from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState

log = logging.getLogger(__name__)

CLARIFY = {
    "which_device": ("Bạn đang hỏi về thiết bị nào?", "Which appliance do you mean?"),
    "several_devices": ("Nhà bạn có nhiều thiết bị khớp, bạn muốn hỏi cái nào?",
                        "Several of your appliances match. Which one?"),
    "unknown_word": ("Mình chưa biết từ này chỉ thiết bị nào. Chọn một, mình sẽ nhớ cho lần sau:",
                     "I don't know which appliance that word means. Pick one and I'll remember:"),
    "data_or_advice": ("Bạn muốn biết mức dùng hay cách tiết kiệm?",
                       "Do you want the usage or how to save?"),
}
TEMPLATES = {
    "other": ("Mình chỉ trả lời được các câu hỏi về điện của nhà bạn: mức dùng, chi phí và cách "
              "tiết kiệm.", "I can only answer questions about your home's electricity: usage, "
              "cost and how to save."),
    "invalid": ("Mình chưa lấy được số liệu cho câu hỏi này. Bạn thử hỏi cụ thể hơn nhé.",
                "I couldn't get the data for this question. Try asking more precisely."),
    "declined": ("Đã huỷ, mình không thay đổi gì.", "Cancelled, nothing was changed."),
    "expired": ("Yêu cầu này đã hết hạn, bạn hỏi lại giúp mình nhé.",
                "That request expired; please ask again."),
    "no_suggestions": ("Hiện chưa có gợi ý tiết kiệm nào cho nhà bạn.",
                       "There are no saving suggestions for your home yet."),
    "no_alerts": ("Nhà bạn chưa có cảnh báo nào.", "Your home has no alerts yet."),
    "no_documents": ("Mình chưa có tài liệu nào trả lời câu hỏi này.",
                     "I have no document that answers this yet."),
    "no_savings": ("Chưa có gợi ý nào được đo kết quả tiết kiệm.",
                   "No accepted suggestion has a measured saving yet."),
}
NO_DATA = {"read_suggestions": "no_suggestions", "list_alerts": "no_alerts",
           "search_knowledge": "no_documents", "get_savings": "no_savings"}


def _t(key: str, vi: bool) -> str:
    return TEMPLATES[key][0 if vi else 1]


def facts_text(state: TurnState) -> str:
    return "; ".join(f"{f.k}: {f.v}" for f in state.get("facts") or [])


def template(state: TurnState) -> str | None:
    """The reply without an LLM, or None when the LLM should word the results."""
    vi = state.get("lang", "vi") == "vi"
    card, outcome = state.get("card"), state.get("outcome")
    if card and card["kind"] == "clarification":
        return CLARIFY[card["reason"]][0 if vi else 1]
    if card and card["kind"] == "confirm":
        args = ", ".join(f"{k}={v}" for k, v in card["args"].items() if v is not None)
        return (f"Bạn có muốn {card['label'].lower()} ({args}) không? Trả lời Có hoặc Không."
                if vi else f"Shall I {card['label'].lower()} ({args})? Answer yes or no.")
    if outcome in ("other", "refused") or (state.get("retrieval") == "none"):
        return _t("other", vi)
    if outcome in ("declined", "expired"):
        return _t(outcome, vi)
    results = [r for r in state.get("results", []) if r.get("ok") is not None]
    good = [r for r in results if r["ok"]]
    if not good:
        return _t("invalid", vi)
    missing = next((r["no_device"] for r in good if r.get("no_device")), None)
    if missing:
        return (f"Mình không tìm thấy thiết bị “{missing}” trong nhà bạn." if vi
                else f"I can't find a device called “{missing}” in your home.")
    if all(r.get("no_data") for r in good):
        key = next((NO_DATA[r["tool"]] for r in good if r["tool"] in NO_DATA), None)
        if key:
            return _t(key, vi)
        live = next((r for r in good if r["tool"] == "nilm_latest"), None)
        if live and (live.get("data") or {}).get("latest_ts"):
            at = dt.datetime.fromisoformat(live["data"]["latest_ts"]).astimezone(
                ZoneInfo(state["home"]["timezone"]))
            minutes = live["args"].get("minutes", 15)
            return (f"Không có dữ liệu mới trong {minutes} phút qua. Dữ liệu mới nhất lúc "
                    f"{at:%H:%M} ngày {at:%d/%m/%Y}." if vi else
                    f"No new data in the last {minutes} minutes. The latest is from "
                    f"{at:%H:%M} on {at:%d/%m/%Y}.")
        latest = state["home"].get("latest_date")
        tail = (f" Dữ liệu mới nhất là ngày {latest}." if vi else f" The latest data is {latest}.")
        return (("Không có dữ liệu cho khoảng thời gian này." if vi
                 else "There is no data for that period.") + (tail if latest else ""))
    return None


async def generate_answer(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    if state["trigger"] in ("schedule", "event"):
        return {"answer": "", "answer_source": "template"}
    text = template(state)
    if text is not None:
        return {"answer": text, "answer_source": "template"}
    good = [r for r in state.get("results", []) if r.get("ok")]
    payload = {
        "question": state.get("question"), "language": state["lang"],
        "user": (state.get("user") or {}).get("name"),
        "skill": state["skill"]["name"] if state.get("skill") else None,
        "skill_goal": state["skill"]["description"] if state.get("skill") else None,
        "skill_instructions": state["skill"]["instructions"] if state.get("skill") else None,
        "results": [{"tool": r["tool"], "data": r.get("data")} for r in good],
        "facts": [f.model_dump() for f in state.get("facts", [])],
        "assumptions": [a for r in good for a in r.get("assumptions", [])],
        "latest_data_date": state["home"].get("latest_date"),
    }
    try:
        text = await llm.text(runtime.context.model(), llm.ANSWER,
                              json.loads(json.dumps(payload, default=str)))
        return {"answer": text.strip(), "answer_source": "llm"}
    except Exception:  # the numbers are in the facts; never fail the turn on the wording
        log.exception("generate_answer: LLM failed, using the facts")
        return {"answer": facts_text(state), "answer_source": "template"}


async def suggest_followups(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    skill = state.get("skill")
    if state.get("card") or not skill or state["trigger"] in ("schedule", "event"):
        return {"followups": []}
    return {"followups": skill.get("followups", [])[:3]}
