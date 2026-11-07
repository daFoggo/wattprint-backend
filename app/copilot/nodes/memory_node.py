"""recall_memory: embed the standalone question once and read long-term memory (spec 5.3)."""

from langgraph.runtime import Runtime

from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState
from ..memory import recall


async def recall_memory(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    ctx, home = runtime.context, state["home"]
    vector = await ctx.embedder().embed_query(state["standalone"])
    memory = {"sessions": [], "facts": []}
    if home.get("memory_enabled", True):
        async with ctx.app()() as s:
            memory = await recall.recall(s, home_id=home["id"],
                                         user_id=(state.get("user") or {}).get("id"),
                                         conversation_id=state.get("conversation_id"),
                                         vector=vector)
    return {"qvec": vector, "memory": memory}
