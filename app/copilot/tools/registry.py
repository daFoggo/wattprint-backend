"""Tool handlers by name: the only code a `copilot.tool` row can run.

A handler is `async def fn(args: ArgsModel, rc: RunContext) -> dict` registered with `@handler`.
Its pydantic model is the tool's JSON Schema (copied to `copilot.tool.parameters` on sync) and
validates every call. The returned dict may hold:

    data      JSON-able result the LLM and the answer read (numbers come from here)
    facts     list[Fact] shown under the answer
    card      a clarification (Unclear.model_dump()) to show instead of an answer
    ok/error  False + message when the call failed (the LLM may retry with fixed arguments)
    no_data   True when the query ran but the period has no data
    sql/unit  for the tool_call row; api: extra fields of the /ask response
"""

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..agents.base_agent import CopilotContext
from ..agents.state import Candidate

FORBIDDEN_ARGS = {"home_id", "user_id", "token", "sql"}  # from RunContext only, never the LLM
# a preset on the left also fixes the arguments on the right (the LLM may not widen it)
LOCKED_WITH = {"device_ids": ("device_type_codes",), "device_id": ("device_type_codes",)}


def locked(preset: dict) -> set[str]:
    """Argument names a skill's preset takes away from the LLM."""
    return set(preset) | {k for name in preset for k in LOCKED_WITH.get(name, ())}


class NoArgs(BaseModel):
    pass


@dataclass
class RunContext:
    """What a handler may use: the home of this run and its connections. Never LLM input."""

    ctx: CopilotContext
    home: dict[str, Any]
    token: str
    lang: str = "vi"
    user: dict[str, Any] | None = None
    terms: list[Candidate] = field(default_factory=list)
    question: str = ""
    conversation_id: str | None = None
    results: dict[str, dict[str, Any]] = field(default_factory=dict)  # by tool name (pipelines)

    @property
    def today(self) -> dt.date:
        return self.ctx.local_today()


@dataclass(frozen=True)
class Handler:
    name: str
    fn: Callable[[Any, RunContext], Awaitable[dict[str, Any]]]
    args: type[BaseModel]
    side_effect: str

    def schema(self) -> dict[str, Any]:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        for spec in schema.get("properties", {}).values():
            spec.pop("title", None)
        return schema


HANDLERS: dict[str, Handler] = {}


def handler(name: str, args: type[BaseModel] = NoArgs, side_effect: str = "read"):
    def register(fn):
        assert not set(args.model_fields) & FORBIDDEN_ARGS, (name, args.model_fields)
        HANDLERS[name] = Handler(name, fn, args, side_effect)
        return fn

    return register


def handlers() -> dict[str, Handler]:
    from . import handlers as _modules  # noqa: F401  registers every handler

    return HANDLERS
