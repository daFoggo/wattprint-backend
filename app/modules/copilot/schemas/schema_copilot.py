import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID | None = None  # none: a new conversation titled by the question
    question: Question
    lang: Literal["vi", "en"] = "vi"


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    pinned: bool
    updated_at: datetime


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    reply: dict[str, Any] | None  # the assistant's structured reply, as `done` streamed it
    feedback: Literal["up", "down"] | None
    created_at: datetime


class ConversationRead(ConversationSummary):
    messages: list[MessageRead]


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    pinned: bool | None = None


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Literal["up", "down"] | None


class Transcript(BaseModel):
    text: str
    language: str | None
    duration: float | None


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
