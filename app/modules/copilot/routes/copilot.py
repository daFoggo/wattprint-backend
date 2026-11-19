import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.dependencies import DbSession
from app.modules.home.api import Membership

from .. import services
from ..schemas import (
    ChatIn,
    ConversationRead,
    ConversationSummary,
    ConversationUpdate,
    FeedbackIn,
    PlanRead,
)

router = APIRouter()
log = logging.getLogger("copilot")


async def _guarded(events: AsyncIterator[str]) -> AsyncIterator[str]:
    """The stream always ends with done or error, even on an unexpected failure."""
    try:
        async for e in events:
            yield e
    except Exception:
        log.exception("copilot answer crashed")
        yield services.event(
            "error", {"code": "copilot_failed", "message": "The answer failed", "reply": None}
        )


@router.post(
    "/chat",
    summary=(
        "Ask Wappi. Server-sent events: `meta` {conversation_id, message_id}, `step` {label, "
        "detail} per tool, `token` {text}, then `done` {message_id, reply} (stored) or `error` "
        "{code, message, reply} (the tools' widgets so far)"
    ),
    response_class=StreamingResponse,
)
async def chat(body: ChatIn, member: Membership, db: DbSession) -> StreamingResponse:
    conversation_id, question_id = await services.ask(
        db, member.user_id, member.home_id, body.conversation_id, body.question
    )
    await db.close()  # the answer opens its own session; this one is done
    return StreamingResponse(
        _guarded(services.answer(member.home_id, conversation_id, question_id, body.lang)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", summary="The user's conversations in this home, pinned first")
async def conversations(member: Membership, db: DbSession) -> list[ConversationSummary]:
    rows = await services.conversations(db, member.user_id, member.home_id)
    return [ConversationSummary.model_validate(c) for c in rows]


@router.get("/conversations/{conversation_id}", summary="One conversation with its messages")
async def conversation(
    conversation_id: uuid.UUID, member: Membership, db: DbSession
) -> ConversationRead:
    c, messages = await services.conversation(db, member.user_id, member.home_id, conversation_id)
    return ConversationRead.model_validate(
        {**ConversationSummary.model_validate(c).model_dump(), "messages": messages}
    )


@router.patch("/conversations/{conversation_id}", summary="Rename or pin a conversation")
async def update_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, member: Membership, db: DbSession
) -> ConversationSummary:
    c = await services.update_conversation(
        db, member.user_id, member.home_id, conversation_id, body.model_dump(exclude_unset=True)
    )
    return ConversationSummary.model_validate(c)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, member: Membership, db: DbSession):
    await services.delete_conversation(db, member.user_id, member.home_id, conversation_id)


@router.put(
    "/messages/{message_id}/feedback", status_code=204, summary="Rate an answer (null clears)"
)
async def feedback(message_id: uuid.UUID, body: FeedbackIn, member: Membership, db: DbSession):
    await services.rate(db, member.user_id, member.home_id, message_id, body.value)


@router.post("/plans/{plan_id}/accept", summary="Start trying a savings plan Wappi proposed")
async def accept_plan(plan_id: uuid.UUID, member: Membership, db: DbSession) -> PlanRead:
    return PlanRead.model_validate(
        await services.accept_plan(db, member.user_id, member.home_id, plan_id)
    )
