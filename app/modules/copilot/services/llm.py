import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings

from ..utils import CopilotUnavailableError

log = logging.getLogger(__name__)


class ProviderError(CopilotUnavailableError):
    """One provider failed. `hard`: the provider itself is the problem (network, 5xx, 429, no
    access), so it rests at once. A soft one (another 4xx) may be this request's fault: it rests
    only when the next provider answers the same request."""

    def __init__(self, message: str = "", *, hard: bool = True):
        super().__init__(message)
        self.hard = hard


HARD_STATUSES = {401, 402, 403, 404, 408, 429}


def is_hard(status: int) -> bool:
    return status >= 500 or status in HARD_STATUSES


@dataclass
class Call:
    id: str
    name: str
    arguments: str = ""

    def args(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.arguments or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


@dataclass
class Turn:
    """One model turn as it streamed: its words (yielded as they come) and the tools it called."""

    text: str = ""
    calls: list[Call] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)  # OpenRouter's: tokens, cached, cost


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key: str
    model: str
    extra: dict[str, Any]


_down: dict[str, float] = {}  # provider name -> monotonic time until which it is left alone


def providers() -> list[Provider]:
    """The providers that have a key, in the configured order."""
    have = {
        "openrouter": Provider(
            "openrouter",
            settings.openrouter_base_url,
            settings.openrouter_api_key,
            settings.openrouter_model,
            {"usage": {"include": True}},
        ),
        "astralx": Provider(
            "astralx",
            settings.astralx_base_url,
            settings.astralx_api_key,
            settings.astralx_chat_model,
            {"stream_options": {"include_usage": True}},
        ),
    }
    names = [n.strip().lower() for n in settings.copilot_llm_order.split(",")]
    return [have[n] for n in names if n in have and have[n].key]


def resting(name: str) -> bool:
    return _down.get(name, 0) > time.monotonic()


async def stream(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, turn: Turn
) -> AsyncIterator[str]:
    """Stream one chat completion from the first provider that answers. One that fails before its
    first word hands over to the next; one that fails midway raises, as part of the answer is
    already out. A provider that is itself down rests for the cooldown, so the next questions do not
    wait on it; the state is per process, which only means each worker learns it on its own."""
    ready = providers()
    if not ready:
        raise CopilotUnavailableError
    live = [p for p in ready if not resting(p.name)] or ready  # all resting: try them anyway
    soft: list[str] = []  # failed in a way that may be this request's fault
    last: CopilotUnavailableError | None = None
    for p in live:
        spoke = False
        try:
            async for delta in _attempt(p, messages, tools, turn):
                spoke = True
                yield delta
        except CopilotUnavailableError as e:
            if getattr(e, "hard", True):
                _down[p.name] = time.monotonic() + settings.copilot_llm_cooldown_s
            else:
                soft.append(p.name)
            if spoke:
                raise
            log.warning("chat provider %s unavailable: %s", p.name, e)
            turn.text, turn.calls, turn.usage, last = "", [], {}, e
        else:
            turn.usage["provider"] = (
                p.name
            )  # AstralX reports no cost: this says whose tokens they were
            for name in soft:  # the same request worked elsewhere: those providers are the problem
                _down[name] = time.monotonic() + settings.copilot_llm_cooldown_s
            _down.pop(p.name, None)
            return
    raise last or CopilotUnavailableError


async def _attempt(
    provider: Provider,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    turn: Turn,
) -> AsyncIterator[str]:
    """One completion on one provider: yield text deltas, fill `turn` with text and tool calls."""
    body: dict[str, Any] = {
        "model": provider.model,
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
        **provider.extra,  # asks for tokens (and cost) in the last chunk
    }
    if tools:
        body["tools"] = tools
    calls: dict[int, Call] = {}
    timeout = httpx.Timeout(settings.copilot_llm_timeout_s, connect=5.0)
    try:
        async with (
            httpx.AsyncClient(base_url=provider.base_url, timeout=timeout) as client,
            client.stream(
                "POST",
                "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {provider.key}"},
            ) as res,
        ):
            if res.status_code != 200:
                await res.aread()
                status = res.status_code
                raise ProviderError(f"LLM answered {status}", hard=is_hard(status))
            async for line in res.aiter_lines():
                if not line.startswith("data:"):
                    continue  # blank keep-alives and ": OPENROUTER PROCESSING" comments
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if "error" in chunk:
                    err = chunk["error"]
                    code = err.get("code")
                    hard = not isinstance(code, int) or is_hard(code)
                    raise ProviderError(str(err.get("message", "")), hard=hard)
                if usage := chunk.get("usage"):
                    turn.usage = usage
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    if text := delta.get("content"):
                        turn.text += text
                        yield text
                    for tc in delta.get("tool_calls") or []:
                        call = calls.setdefault(tc.get("index", 0), Call(tc.get("id", ""), ""))
                        fn = tc.get("function") or {}
                        call.id = tc.get("id") or call.id
                        call.name += fn.get("name") or ""
                        call.arguments += fn.get("arguments") or ""
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        raise ProviderError(f"LLM unreachable or garbled: {e!r}") from e
    turn.calls = [calls[i] for i in sorted(calls) if calls[i].name]
