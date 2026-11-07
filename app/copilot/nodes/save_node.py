"""save_turn: the assistant message and the run's tool_call rows (short-term memory)."""

import uuid

from langgraph.runtime import Runtime

from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState
from ..memory import short_term


async def save_turn(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    queries = list(state.get("queries", []))
    chosen = (state.get("skill") or {}).get("code")
    for q in queries:
        if q["tool"] == "skill_search":
            q["input"] = {**q["input"], "chosen": chosen}
    home_id = uuid.UUID(state["home"]["id"])
    async with runtime.context.app()() as s:
        if state["trigger"] in ("schedule", "event"):
            await short_term.save_calls(s, queries, None, home_id)
            await s.commit()
            return {"message_id": None}
        message_id = await short_term.save_reply(s, state["conversation_id"],
                                                 state.get("answer") or "", queries, home_id)
    return {"message_id": message_id}
