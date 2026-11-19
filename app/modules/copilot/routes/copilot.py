import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import Response, StreamingResponse

from app.common.exceptions import UnprocessableError
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
    Transcript,
)
from ..utils import AudioTooLargeError, RateLimitedError, VoiceUnavailableError

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
    # Personal data is replaced before it is stored or reaches the model (kinds logged, not values).
    question, found = services.redact(body.question, body.lang)
    if found:
        log.info("copilot question redacted: %s", found)
    conversation_id, question_id = await services.ask(
        db, member.user_id, member.home_id, body.conversation_id, question
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
        db, member.user_id, member.home_id, conversation_id, body.model_dump(exclude_none=True)
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


MAX_AUDIO = 10 * 1024 * 1024  # about 10 minutes of Opus: far more than one question
VOICE_PER_MINUTE = 30  # speech to text and text to speech calls per user (each one is paid)
_voice_calls: dict[uuid.UUID, deque[float]] = defaultdict(deque)


def _voice_quota(user_id: uuid.UUID) -> None:
    # shortcut: counted per API process, so N processes allow N times as much; move the count to the
    # database or Redis when the API runs several workers.
    now = time.monotonic()
    calls = _voice_calls[user_id]
    while calls and now - calls[0] > 60:
        calls.popleft()
    if len(calls) >= VOICE_PER_MINUTE:
        raise RateLimitedError(
            "Too many voice requests in a minute",
            code="voice_rate_limited",
            headers={"Retry-After": "60"},
        )
    calls.append(now)


@router.post(
    "/voice/transcribe",
    summary="Speech to text: the request body is the recording (Content-Type audio/webm, "
    "audio/ogg, audio/mp4, audio/mpeg or audio/wav), at most 10 MB",
)
async def transcribe(
    request: Request,
    member: Membership,
    content_type: Annotated[str, Header()],
    lang: Annotated[Literal["vi", "en"], Query()] = "vi",
) -> Transcript:
    _voice_quota(member.user_id)
    kind = content_type.split(";")[0].strip().lower()  # "audio/webm;codecs=opus"
    if kind not in services.EXT:
        raise UnprocessableError("Unsupported audio type", code="audio_type_unsupported")
    audio = bytearray()
    async for chunk in request.stream():
        audio += chunk
        if len(audio) > MAX_AUDIO:
            raise AudioTooLargeError
    if not audio:
        raise UnprocessableError("The recording is empty", code="audio_empty")
    return Transcript.model_validate(await services.transcribe(bytes(audio), kind, lang))


@router.get(
    "/messages/{message_id}/speech",
    summary="One of Wappi's answers read aloud: an MP3 stream that starts after its first sentence",
    response_class=StreamingResponse,
    responses={200: {"content": {"audio/mpeg": {}}}},
)
async def speech(
    message_id: uuid.UUID,
    member: Membership,
    db: DbSession,
    lang: Annotated[Literal["vi", "en"], Query()] = "vi",
) -> StreamingResponse:
    text = await services.answer_text(db, member.user_id, member.home_id, message_id)
    kept = await services.kept_speech(db, message_id, lang)
    await db.close()
    if kept is not None:  # heard before: no new reading, nothing paid, not counted
        return Response(kept, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
    _voice_quota(member.user_id)
    audio = services.speech(text, lang)
    first = await anext(
        audio, b""
    )  # a failure before any sound is an error status, not a cut stream

    async def stream() -> AsyncIterator[bytes]:
        read = [first]
        try:
            yield first
            async for piece in audio:
                read.append(piece)
                yield piece
        except VoiceUnavailableError:
            return  # logged; the reading ends where the voice failed, and is not kept
        finally:
            await audio.aclose()  # the listener left: voice nothing more
        if first:
            await services.keep_speech(message_id, lang, b"".join(read))

    return StreamingResponse(
        stream(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"}
    )
