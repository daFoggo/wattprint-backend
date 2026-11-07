"""ingress: the input guard of every run (spec 5.2). No LLM."""

import re
import time
from collections import defaultdict, deque

from langgraph.runtime import Runtime

from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState
from ..config.settings import LLM
from ..utils.helpers import detect_lang

LIMITS = LLM["limits"]
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]")
INJECTION = re.compile(
    r"ignore (all|any|previous|the|your)\b|bỏ qua (mọi|tất cả|các)?\s*(quy tắc|hướng dẫn|lệnh)"
    r"|bo qua (moi|tat ca|cac)?\s*(quy tac|huong dan)|system prompt"
    r"|\b(drop|truncate|alter)\s+table\b|\bdelete\s+from\b|\binsert\s+into\b", re.IGNORECASE)
# ponytail: per-process window; a shared limiter (Redis) when the API runs several workers
_RECENT: dict[str, deque] = defaultdict(deque)


class RejectedError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _rate_limit(user_id: str) -> None:
    now, window = time.monotonic(), _RECENT[user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= LIMITS["messages_per_minute"]:
        raise RejectedError(429, "too many messages; wait a minute")
    window.append(now)


async def ingress(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    trigger = state.get("trigger") or "chat"
    if trigger in ("schedule", "event"):
        return {"trigger": trigger, "lang": "vi"}
    question = _CONTROL.sub("", state.get("question") or "").strip()
    if trigger == "chat":
        if not 1 <= len(question) <= LIMITS["message_chars"]:
            raise RejectedError(400, f"the message must be 1 to {LIMITS['message_chars']} "
                                     "characters")
        _rate_limit(state["user_id"])
    return {"trigger": trigger, "question": question,
            "lang": detect_lang(question) if question else "vi",
            "flags": ["injection"] if INJECTION.search(question) else []}
