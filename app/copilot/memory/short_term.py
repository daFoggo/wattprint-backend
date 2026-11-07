"""Short-term memory: one conversation's messages (copilot.conversation / copilot.message).

No LangGraph checkpointer: each question is one run, and these rows are the history.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Conversation, Message, ToolCall

HISTORY_MESSAGES = 6


async def open_conversation(s: AsyncSession, home_id: uuid.UUID, user_id: uuid.UUID,
                            conversation_id: str | None, question: str
                            ) -> tuple[str, list[dict[str, str]]]:
    """The conversation (new when no id), its last messages oldest first, and the question
    added as a user message. The caller commits."""
    conv = await s.get(Conversation, uuid.UUID(conversation_id)) if conversation_id else None
    if conversation_id and (conv is None or conv.home_id != home_id or conv.user_id != user_id):
        raise LookupError("conversation not found")
    if conv is None:
        conv = Conversation(home_id=home_id, user_id=user_id, title=question[:80])
        s.add(conv)
        await s.flush()
    history = (
        await s.execute(
            select(Message.role, Message.content)
            .where(Message.conversation_id == conv.id,
                   Message.role.in_(("user", "assistant")))
            .order_by(Message.created_at.desc())
            .limit(HISTORY_MESSAGES)
        )
    ).all()
    s.add(Message(conversation_id=conv.id, role="user", content=question))
    return str(conv.id), [{"role": r.role, "content": r.content} for r in reversed(history)]


async def save_calls(s: AsyncSession, queries: list[dict[str, Any]],
                     message_id: uuid.UUID | None, home_id: uuid.UUID) -> None:
    """tool_call rows of a run; `update_id` finishes a pending call (the user said yes)."""
    for q in queries:
        if q.get("update_id"):
            row = await s.get(ToolCall, uuid.UUID(q["update_id"]))
            row.input = {**row.input, **q["input"]}
            row.ok, row.duration_ms = q["ok"], q.get("duration_ms")
            continue
        s.add(ToolCall(id=uuid.UUID(q["id"]) if q.get("id") else uuid.uuid4(),
                       message_id=message_id, home_id=home_id, tool=q["tool"], input=q["input"],
                       sql_text=q.get("sql"), unit=q.get("unit"),
                       duration_ms=q.get("duration_ms"), ok=q["ok"]))


async def save_reply(s: AsyncSession, conversation_id: str, answer: str,
                     queries: list[dict[str, Any]], home_id: uuid.UUID) -> str:
    """The assistant message and the tool calls it was built on; returns the message id."""
    msg = Message(conversation_id=uuid.UUID(conversation_id), role="assistant", content=answer)
    s.add(msg)
    await s.flush()
    await save_calls(s, queries, msg.id, home_id)
    await s.commit()
    return str(msg.id)


async def last_turn(s: AsyncSession, conversation_id: str) -> dict[str, Any] | None:
    """The previous assistant turn of this conversation: its skill, tool calls with their
    arguments and results, and a write still waiting for the user's yes."""
    msg_id = await s.scalar(
        select(Message.id).where(Message.conversation_id == uuid.UUID(conversation_id),
                                 Message.role == "assistant")
        .order_by(Message.created_at.desc()).limit(1))
    if msg_id is None:
        return None
    rows = (await s.execute(select(ToolCall).where(ToolCall.message_id == msg_id)
                            .order_by(ToolCall.created_at))).scalars().all()
    turn: dict[str, Any] = {"message_id": str(msg_id), "skill": None, "calls": [],
                            "pending": None}
    for r in rows:
        if r.tool == "skill_search":
            turn["skill"] = (r.input or {}).get("chosen")
        elif r.tool != "miss":
            call = {"id": str(r.id), "tool": r.tool, "args": (r.input or {}).get("args", {}),
                    "ok": r.ok, "created_at": r.created_at.isoformat()}
            turn["calls"].append(call)
            if r.ok is None:
                turn["pending"] = {**call, "skill": (r.input or {}).get("skill")}
    return turn
