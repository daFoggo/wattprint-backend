import logging
import re

import httpx

from app.config import settings

log = logging.getLogger("copilot.guard")

# Asking the model to drop its rules or show its prompt. The tools are scoped to the user's home in
# code whatever the model is told, so this is about what Wappi says: such a question is declined
# before any model reads it. Phrases, not words, so that "bỏ qua" in an energy question passes.
INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override)\b.{0,30}\b(?:previous|prior|above|earlier|all|your|"
    r"system)\b.{0,30}\b(?:instructions?|rules|prompts?|guidelines)\b"
    r"|\b(?:system prompt|developer mode|jailbreak|do anything now|dan mode)\b"
    r"|\byou are now\b"
    r"|\b(?:reveal|print|show|repeat)\b.{0,30}\b(?:system|hidden|initial) (?:prompt|instructions)"
    r"|(?:bỏ qua|phớt lờ|quên|vô hiệu hóa|bỏ hết).{0,30}(?:hướng dẫn|chỉ dẫn|quy tắc|luật|lệnh)"
    r".{0,20}(?:trước|ở trên|ban đầu|hệ thống|của bạn|đã cho)"
    r"|prompt hệ thống|lời nhắc hệ thống|chế độ nhà phát triển"
    r"|(?:từ giờ|bây giờ|kể từ giờ) bạn là"
    r"|(?:in ra|tiết lộ|cho xem|nhắc lại).{0,20}(?:prompt|hướng dẫn hệ thống|chỉ dẫn ban đầu)",
    re.IGNORECASE,
)


def injection(question: str) -> bool:
    return INJECTION.search(question) is not None


async def unsafe(question: str) -> str | None:
    """Llama Guard's hazard category for the question (S1 violent crimes, S2 other crimes such as
    stealing power...), or None when it is safe. A guard that cannot answer lets the question
    through (logged): the tools stay scoped either way, and Wappi stays usable."""
    if not (settings.openrouter_api_key and settings.copilot_guard_model):
        return None
    try:
        async with httpx.AsyncClient(
            base_url=settings.openrouter_base_url, timeout=httpx.Timeout(10.0, connect=5.0)
        ) as client:
            r = await client.post(
                "/chat/completions",
                json={
                    "model": settings.copilot_guard_model,
                    "messages": [{"role": "user", "content": question}],
                },
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            )
            r.raise_for_status()
            verdict = r.json()["choices"][0]["message"]["content"].split()
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
        log.warning("guard unavailable, question let through: %r", e)
        return None
    if verdict[:1] != ["unsafe"]:
        return None
    return verdict[1] if len(verdict) > 1 else "unsafe"
