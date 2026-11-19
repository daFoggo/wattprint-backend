import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, Message, Suggestion, SuggestionFeedback
from ..utils import (
    ConversationNotFoundError,
    MessageNotFoundError,
    PlanNotFoundError,
    RateLimitedError,
)

PER_MINUTE = 20  # questions per user per minute, across their conversations


async def _own(
    s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    c = await s.get(Conversation, conversation_id)
    if c is None or c.user_id != user_id or c.home_id != home_id:
        raise ConversationNotFoundError
    return c


async def ask(
    s: AsyncSession,
    user_id: uuid.UUID,
    home_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    question: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Store the question (in a new conversation when none is named): (conversation, message)."""
    recent = await s.scalar(
        select(func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.user_id == user_id,
            Message.role == "user",
            Message.created_at > datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    if recent >= PER_MINUTE:
        raise RateLimitedError(headers={"Retry-After": "60"})
    if conversation_id is None:
        c = Conversation(user_id=user_id, home_id=home_id, title=question[:80])
        s.add(c)
        await s.flush()
    else:
        c = await _own(s, user_id, home_id, conversation_id)
    m = Message(conversation_id=c.id, role="user", content=question)
    s.add(m)
    await s.flush()
    c.updated_at = func.now()
    await s.commit()
    return c.id, m.id


async def conversations(s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID):
    """Pinned first, then most recent."""
    return (
        await s.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.home_id == home_id)
            .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
            .limit(100)
        )
    ).all()


async def conversation(s, user_id, home_id, conversation_id):
    c = await _own(s, user_id, home_id, conversation_id)
    messages = (
        await s.scalars(
            select(Message)
            .where(Message.conversation_id == c.id, Message.role.in_(("user", "assistant")))
            .order_by(Message.id)
        )
    ).all()
    return c, messages


async def update_conversation(s, user_id, home_id, conversation_id, changes: dict) -> Conversation:
    c = await _own(s, user_id, home_id, conversation_id)
    for k, v in changes.items():
        setattr(c, k, v)
    await s.commit()
    await s.refresh(c)
    return c


async def delete_conversation(s, user_id, home_id, conversation_id) -> None:
    c = await _own(s, user_id, home_id, conversation_id)
    await s.execute(delete(Conversation).where(Conversation.id == c.id))
    await s.commit()


async def answer_text(s, user_id, home_id, message_id: uuid.UUID) -> str:
    """The text of one of Wappi's answers to this user in this home."""
    text = await s.scalar(
        select(Message.content)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.id == message_id,
            Message.role == "assistant",
            Conversation.user_id == user_id,
            Conversation.home_id == home_id,
        )
    )
    if text is None:
        raise MessageNotFoundError
    return text


async def rate(s, user_id, home_id, message_id: uuid.UUID, value: str | None) -> None:
    await answer_text(s, user_id, home_id, message_id)
    await s.execute(update(Message).where(Message.id == message_id).values(feedback=value))
    await s.commit()


async def accept_plan(s, user_id, home_id, plan_id: uuid.UUID) -> Suggestion:
    """Start trying a plan; its saving is measured 14 days later against the 14 days before."""
    plan = await s.get(Suggestion, plan_id)
    if plan is None or plan.home_id != home_id or plan.kind != "plan":
        raise PlanNotFoundError
    if plan.status in ("proposed", "shown"):
        plan.status = "accepted"
        s.add(SuggestionFeedback(suggestion_id=plan.id, user_id=user_id, action="accept"))
        await s.commit()
    return plan
