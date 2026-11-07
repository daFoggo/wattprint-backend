"""find_skills: the skills this home may use, closest to the question (spec 5.2, 6). No LLM."""

from langgraph.runtime import Runtime

from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState
from ..skills import retrieval

MEMORY_BOOST = 0.01  # a skill of the recalled sessions ranks a little higher, nothing more


async def find_skills(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    home_id = state["home"]["id"]
    async with runtime.context.app()() as s:
        found = await retrieval.search(s, home_id, state["qvec"])
    recalled = {c for m in state.get("memory", {}).get("sessions", []) for c in m["skills_used"]}
    for c in found:
        if c["code"] in recalled:
            c["sim"] = round(c["sim"] + MEMORY_BOOST, 4)
    found.sort(key=lambda c: -c["sim"])
    case = retrieval.case_of(found)
    previous = (state.get("last_turn") or {}).get("skill")
    if previous:
        # the last turn's skill is always a candidate; first for a follow-up completed from it
        top = next((c for c in found if c["code"] == previous),
                   {"code": previous, "name": previous, "description": "", "sim": None,
                    "previous": True})
        rest = [c for c in found if c is not top]
        follow_up = bool((state.get("rewrite") or {}).get("carried"))
        found = [top, *rest] if follow_up else [*rest, top] if top not in found else found
        case = "choose"
    return _out(state, found, case)


def _out(state: TurnState, found: list[dict], case: str) -> dict:
    return {"candidates": found, "retrieval": case,
            "queries": [{"tool": "skill_search", "ok": True, "input": {
                "question": state["standalone"], "case": case,
                "candidates": [{"code": c["code"], "sim": c["sim"]} for c in found]}}]}
