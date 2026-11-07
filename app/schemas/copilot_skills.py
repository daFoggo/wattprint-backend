import uuid
from typing import Any

from pydantic import BaseModel, Field


class SkillToolIn(BaseModel):
    tool: str = Field(description="tool name, from GET /copilot/tools")
    preset: dict[str, Any] = Field(default_factory=dict,
                                   description="fixed arguments; keys from the tool's presettable")


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=600, description="when to use it")
    instructions: str = Field("", max_length=500)
    examples: list[str] = Field(min_length=2, max_length=30)
    tools: list[SkillToolIn] = Field(min_length=1, max_length=5)
    followups: list[str] = Field(default_factory=list, max_length=3)


class SkillPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    description: str | None = Field(None, min_length=1, max_length=600)
    instructions: str | None = Field(None, max_length=500)
    examples: list[str] | None = Field(None, min_length=2, max_length=30)
    tools: list[SkillToolIn] | None = Field(None, min_length=1, max_length=5)
    followups: list[str] | None = Field(None, max_length=3)


class ExamplesIn(BaseModel):
    examples: list[str] = Field(min_length=1, max_length=30)


class EnabledIn(BaseModel):
    enabled: bool


class TryIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class SkillOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    instructions: str
    mode: str
    triggers: list[str]
    household: bool
    enabled: bool
    embed_status: str
    tools: list[dict[str, Any]]
    examples: list[dict[str, Any]] = Field(description="id, text, mine (added by this home)")
    followups: list[str]


class ToolOut(BaseModel):
    name: str
    label_vi: str
    label_en: str
    description: str
    category: str
    side_effect: str
    presettable: dict[str, Any] = Field(description="argument name -> its JSON Schema")


class TryOut(BaseModel):
    case: str
    candidates: list[dict[str, Any]]
    tools: list[str] = Field(description="the tools the top skill would offer")


class MemoryOut(BaseModel):
    enabled: bool
    facts: list[dict[str, Any]]
    sessions: list[dict[str, Any]]
