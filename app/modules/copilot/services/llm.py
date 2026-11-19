import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings

from ..utils import CopilotUnavailableError


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


async def stream(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, turn: Turn
) -> AsyncIterator[str]:
    """Stream one chat completion: yield text deltas, fill `turn` with the text and tool calls."""
    if not settings.openrouter_api_key:
        raise CopilotUnavailableError
    body: dict[str, Any] = {
        "model": settings.openrouter_model,
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
    }
    if tools:
        body["tools"] = tools
    calls: dict[int, Call] = {}
    timeout = httpx.Timeout(settings.copilot_llm_timeout_s, connect=5.0)
    try:
        async with (
            httpx.AsyncClient(base_url=settings.openrouter_base_url, timeout=timeout) as client,
            client.stream(
                "POST",
                "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            ) as res,
        ):
            if res.status_code != 200:
                await res.aread()
                raise CopilotUnavailableError(f"LLM answered {res.status_code}")
            async for line in res.aiter_lines():
                if not line.startswith("data:"):
                    continue  # blank keep-alives and ": OPENROUTER PROCESSING" comments
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if "error" in chunk:
                    raise CopilotUnavailableError(str(chunk["error"].get("message", "")))
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
        raise CopilotUnavailableError(f"LLM unreachable or garbled: {e!r}") from e
    turn.calls = [calls[i] for i in sorted(calls) if calls[i].name]
