"""Long-term memory for a new turn: summaries of the home's OTHER sessions close to the question
(weighted by recency) and the household facts. Never a source of numbers for the answer."""

import datetime as dt
import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import text

from ..config.settings import LLM

CFG = LLM["retrieval"]

SESSIONS = text("""
SELECT conversation_id::text AS conversation_id, summary, topics, skills_used, ended_at,
       1 - (embedding <=> CAST(:v AS vector)) AS sim
FROM copilot.session_summary
WHERE home_id = :home AND conversation_id <> :conv
ORDER BY embedding <=> CAST(:v AS vector) LIMIT 10
""")
FACTS = text("""
SELECT id, kind, key, value FROM copilot.home_memory
WHERE home_id = :home AND (user_id IS NULL OR user_id = :user) AND confidence >= 0.5
  AND last_seen_at > now() - interval '90 days'
ORDER BY confidence DESC, last_seen_at DESC LIMIT 8
""")


async def recall(session, *, home_id: str, user_id: str | None, conversation_id: str | None,
                 vector: list[float]) -> dict[str, Any]:
    home = uuid.UUID(home_id)
    conv = uuid.UUID(conversation_id) if conversation_id else uuid.UUID(int=0)
    now = dt.datetime.now(UTC)
    sessions = []
    for r in await session.execute(SESSIONS, {"home": home, "conv": conv, "v": str(vector)}):
        if r.sim < CFG["memory_min_sim"]:
            continue
        age = (now - r.ended_at).total_seconds() / 86400
        score = r.sim * 0.5 ** (age / CFG["memory_half_life_days"])
        sessions.append({"conversation_id": r.conversation_id, "summary": r.summary,
                         "topics": list(r.topics), "skills_used": list(r.skills_used),
                         "ended_at": r.ended_at.isoformat(), "sim": round(float(r.sim), 3),
                         "score": round(score, 3)})
    sessions.sort(key=lambda s: -s["score"])
    user = uuid.UUID(user_id) if user_id else None
    facts = [{"id": r.id, "kind": r.kind, "key": r.key, "value": r.value}
             for r in await session.execute(FACTS, {"home": home, "user": user})]
    return {"sessions": sessions[:3], "facts": facts}
