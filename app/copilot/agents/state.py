"""Graph states and the shapes the LLM fills.

State holds plain values and Pydantic models only (`langgraph dev` checkpoints it): sessions and
the chat model come from CopilotContext.
"""

import datetime as dt
import operator
import uuid
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field

Intent = Literal["data", "cost", "advice", "unclear", "other"]
Measure = Literal["energy", "average_power", "peak_power", "cycles", "cycle_energy"]
Source = Literal["measured", "estimated", "best"]
Grain = Literal["none", "hour", "day", "week", "month"]
GroupBy = Literal["none", "device", "hour_of_day", "weekday"]


# --- shapes ---


class Candidate(BaseModel):
    """A lexicon entry the question's words matched."""

    source: Literal["device", "room", "device_type", "term"]
    kind: str  # device | device_type | time_window | threshold
    ref: str | None = None  # device id or device type code
    phrase: str
    score: float
    device_ids: list[str] = []  # the home's devices it stands for
    device_names: list[str] = []
    target: dict[str, Any] | None = None  # a term's target
    from_history: bool = False  # matched the previous question, not this one


class Decision(BaseModel):
    """What `decide` returns. Ids must come from the candidates; dates are local days."""

    intent: Intent = Field(description="data: a number from readings; cost: money in VND; "
                           "advice: how to save; unclear: cannot pick one meaning; other: "
                           "not about this home's electricity")
    device_ids: list[str] = Field(default=[], description="candidate device ids; empty = home")
    device_type_codes: list[str] = Field(default=[], description="candidate device type codes")
    start: dt.date | None = Field(default=None, description="first local day, inclusive")
    end: dt.date | None = Field(default=None, description="last local day, inclusive")
    measure: Measure | None = None
    source: Source | None = Field(default=None, description="measured (plug or main meter), "
                                  "estimated (NILM), best (default)")
    grain: Grain = "none"
    group_by: GroupBy = "none"
    compare_to: Literal["none", "previous_period"] = "none"
    order: Literal["desc", "asc"] | None = None
    top_n: int | None = Field(default=None, ge=1, le=1000)
    unmatched: list[str] = Field(default=[], description="words naming an appliance that "
                                 "matched no candidate")
    assumptions: list[str] = Field(default=[], description="defaults you assumed")


class QueryGoal(BaseModel):
    """A checked, complete data question. Only `sql.build` turns it into SQL."""

    measure: Measure = "energy"
    target: Literal["whole_home", "devices"] = "whole_home"
    device_ids: list[uuid.UUID] = []
    source: Source = "measured"  # "best" is resolved before building (plug coverage)
    start: dt.date
    end: dt.date
    grain: Grain = "none"
    group_by: GroupBy = "none"
    compare_to: Literal["none", "previous_period"] = "none"
    order: Literal["desc", "asc"] | None = None
    top_n: int | None = Field(default=None, ge=1, le=1000)


class Option(BaseModel):
    label: str
    # what tapping it sends back: a term to save and/or the question to ask
    term: dict[str, Any] | None = None
    question: str | None = None


class Unclear(BaseModel):
    reason: str
    options: list[Option]


class Invalid(BaseModel):
    message: str
    fixable: bool = True  # False: answer with the message, no repair


class Phrasing(BaseModel):
    """A suggestion's text; numbers only as {placeholders} filled from the facts."""

    title: str
    body: str


class Fact(BaseModel):
    """One key/value line shown under an answer (the mobile app's ChatFact)."""

    k: str
    v: str


# --- graph state (one graph: chat, confirm, schedule and event runs) ---


class TurnInput(TypedDict, total=False):
    trigger: Literal["chat", "confirm", "schedule", "event"]
    question: str  # chat: the user's words
    user_id: str  # chat and confirm
    conversation_id: str | None  # chat (optional), confirm, event (the session to summarise)
    confirm_call_id: str | None  # confirm: the pending tool_call
    home_id: str  # schedule and event
    skill_code: str  # schedule and event: the skill to run


class TurnState(TurnInput, total=False):
    lang: Literal["vi", "en"]
    flags: Annotated[list[str], operator.add]  # why something was blocked or replaced
    user: dict[str, Any] | None  # id, name, role
    home: dict[str, Any]  # id, name, timezone, tariff, cycle day, latest_date, tracked, devices
    history: list[dict[str, str]]  # short-term memory: last messages of this conversation
    last_turn: dict[str, Any] | None  # short-term memory: previous turn's skill and tool calls
    token: str  # scope token of this run (read-only login)
    terms: list[Candidate]  # linked words of the question (and the previous one)
    dates: dict[str, str] | None  # resolved local dates {start, end}
    standalone: str  # the question made standalone (rewrite_question)
    rewrite: dict[str, Any]  # method (none / rule / llm), carried devices
    qvec: list[float]  # the standalone question's embedding (recall_memory, find_skills)
    memory: dict[str, Any]  # long-term memory: other sessions' summaries, household facts
    candidates: list[dict[str, Any]]  # skills found: code, name, sim
    retrieval: Literal["choose", "none", "given"]
    skill: dict[str, Any] | None  # chosen skill with its tools (retrieval.load_skill)
    plan: list[dict[str, Any]]  # tool calls of this round: id, tool, args, source
    transcript: list[dict[str, Any]]  # agent rounds: calls and their results, for the next round
    rounds: int
    failed_rounds: int
    results: Annotated[list[dict[str, Any]], operator.add]  # every tool call of the run
    tool_data: dict[str, Any]  # latest data by tool name (pipelines read earlier steps)
    facts: Annotated[list[Fact], operator.add]
    card: dict[str, Any] | None  # clarification or confirmation instead of an answer
    api: dict[str, Any]  # result / cost / suggestions for the /ask response
    outcome: str | None  # other / declined / refused / no_tool
    answer: str
    answer_source: Literal["llm", "template"]
    followups: list[str]
    message_id: str | None
    queries: Annotated[list[dict[str, Any]], operator.add]  # tool_call rows to save
    steps: Annotated[list[str], operator.add]
    timings: Annotated[list[dict[str, Any]], operator.add]
