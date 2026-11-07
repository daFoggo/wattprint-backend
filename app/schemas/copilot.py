import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: uuid.UUID | None = None
    confirm_call_id: uuid.UUID | None = Field(
        None, description="answer a confirmation card: the call it showed (question: 'Có')")


class FactOut(BaseModel):
    """One key/value line under an answer (the mobile app's ChatFact)."""

    k: str
    v: str


class OptionOut(BaseModel):
    label: str
    question: str | None = Field(None, description="send this as the next question")
    term: dict[str, Any] | None = Field(
        None, description="POST this to /copilot/terms first, so the word is remembered"
    )


class ClarificationOut(BaseModel):
    reason: Literal["which_device", "several_devices", "unknown_word", "data_or_advice"]
    options: list[OptionOut]


class ResultOut(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str = Field(description="the query that ran; values were bound as $n parameters")
    unit: str
    coverage: float | None = Field(None, description="share of the period's minutes with data")
    source: Literal["measured", "estimated"]


class ChatMessageOut(BaseModel):
    """A message in the mobile app's ChatMessage shape."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: str
    who: Literal["ai", "me"]
    text: str
    facts: list[FactOut] = []
    cta: str | None = None
    cta_desc: str | None = Field(None, alias="ctaDesc")
    created_at: dt.datetime | None = None


class SuggestionOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    device: str | None = None
    expected_kwh: float | None = None
    expected_amount: float | None = Field(None, description="VND per month, VAT included")
    status: str
    evidence: dict[str, Any] = {}
    created_at: dt.datetime | None = None
    measured_saving: dict[str, Any] | None = Field(
        None, description="7 days after acceptance: baseline_kwh, actual_kwh, saved_kwh, method"
    )


class AskOut(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    facts: list[FactOut] = []
    assumptions: list[str] = []
    steps: list[str] = []
    result: ResultOut | None = None
    cost: dict[str, Any] | None = None
    clarification: ClarificationOut | None = None
    suggestions: list[dict[str, Any]] | None = None
    confirm: dict[str, Any] | None = Field(
        None, description="a write waiting for the user's yes: call_id, tool, label, args")
    skill: dict[str, Any] | None = Field(None, description="the skill that answered")
    retrieval: dict[str, Any] = Field(
        default_factory=dict, description="case, standalone question, candidates with scores")
    tools: list[dict[str, Any]] = Field(default_factory=list,
                                        description="tool calls: tool, args, ok, ms")
    timings: list[dict[str, Any]] = Field(default_factory=list, description="node, ms")
    followups: list[str] = []
    memory: list[dict[str, Any]] = Field(default_factory=list,
                                         description="earlier sessions recalled")
    message: ChatMessageOut


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


TermKind = Literal["device", "device_type", "time_window", "threshold"]


class TermIn(BaseModel):
    phrase: str = Field(min_length=1, max_length=120)
    kind: TermKind
    target: dict[str, Any] = Field(
        description="device {device_id}; device_type {code}; time_window {start_hour, "
        "end_hour}; threshold {measure, op, value}"
    )
    created_from_message_id: uuid.UUID | None = None


class TermPatch(BaseModel):
    phrase: str | None = Field(None, min_length=1, max_length=120)
    target: dict[str, Any] | None = None


class TermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phrase: str
    match_key: str
    kind: str
    target: dict[str, Any]
    created_at: dt.datetime


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: dict[str, Any] = Field(description="see app/copilot/utils/rules.py")
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    body: dict[str, Any] | None = None
    enabled: bool | None = None


class RuleOut(BaseModel):
    id: uuid.UUID
    name: str
    motif: str
    body: dict[str, Any]
    suggest_kind: str
    enabled: bool
    version: int
    shared: bool
    dry_run_hits: int | None = Field(None, description="times it would have fired, last 7 days")


class FeedbackIn(BaseModel):
    action: Literal["accept", "reject", "snooze", "done"]
    note: str | None = Field(None, max_length=500)


class RefreshOut(BaseModel):
    stored: int
    suggestions: list[SuggestionOut]
