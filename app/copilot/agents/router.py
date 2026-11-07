"""The orchestrator: one compiled graph for every trigger (chat, confirm, schedule, event).

    ingress → load_context ─┬─ chat ─→ rewrite_question → recall_memory → find_skills ─┐
                            ├─ schedule / event ───────────────────────────→ decide ←──┘
                            ├─ confirm ─→ act                               decide ⇄ act
                            └─ declined / expired ─→ generate_answer
    … → generate_answer → guard_output → suggest_followups → save_turn

No checkpointer: each run is one request; conversation memory is copilot.message + tool_call.
The API router, the CLIs, the tests and langgraph.json use `copilot_graph`.
"""

import functools
import time
from typing import Literal

from langgraph.graph import END, START, StateGraph

from ..nodes.action_node import act, route_after_act
from ..nodes.answer_node import generate_answer, suggest_followups
from ..nodes.context_node import load_context
from ..nodes.decision_node import decide, route_after_decide
from ..nodes.guard_node import guard_output
from ..nodes.ingress_node import ingress
from ..nodes.memory_node import recall_memory
from ..nodes.rewrite_node import rewrite_question
from ..nodes.save_node import save_turn
from ..nodes.skill_search_node import find_skills
from .base_agent import CopilotContext
from .state import TurnInput, TurnState

NODES = (ingress, load_context, rewrite_question, recall_memory, find_skills, decide, act,
         generate_answer, guard_output, suggest_followups, save_turn)


def _timed(fn):
    """Each node's name in `steps` and its wall time in `timings` (the latency metrics)."""

    @functools.wraps(fn)
    async def node(state, runtime):
        t0 = time.perf_counter()
        out = await fn(state, runtime) or {}
        ms = round((time.perf_counter() - t0) * 1000)
        return {**out, "steps": [fn.__name__], "timings": [{"node": fn.__name__, "ms": ms}]}

    return node


def route_after_context(state: TurnState) -> Literal[
        "rewrite_question", "decide", "act", "generate_answer"]:
    if state.get("outcome") in ("declined", "expired"):
        return "generate_answer"
    if state["trigger"] == "confirm":
        return "act"
    if state["trigger"] in ("schedule", "event"):
        return "decide"
    return "rewrite_question"


def route_after_search(state: TurnState) -> Literal["decide", "generate_answer"]:
    return "generate_answer" if state["retrieval"] == "none" else "decide"


def _graph():
    g = StateGraph(TurnState, context_schema=CopilotContext, input_schema=TurnInput)
    for fn in NODES:
        g.add_node(fn.__name__, _timed(fn))
    g.add_edge(START, "ingress")
    g.add_edge("ingress", "load_context")
    g.add_conditional_edges("load_context", route_after_context)
    g.add_edge("rewrite_question", "recall_memory")
    g.add_edge("recall_memory", "find_skills")
    g.add_conditional_edges("find_skills", route_after_search)
    g.add_conditional_edges("decide", route_after_decide)
    g.add_conditional_edges("act", route_after_act)
    g.add_edge("generate_answer", "guard_output")
    g.add_edge("guard_output", "suggest_followups")
    g.add_edge("suggest_followups", "save_turn")
    g.add_edge("save_turn", END)
    return g.compile(name="copilot")


copilot_graph = _graph()
