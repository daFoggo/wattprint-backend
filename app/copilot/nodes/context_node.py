"""load_context: who asks, which home, the conversation (short-term memory), the scope token;
a pending write when the message confirms or declines it (spec 5.2). No LLM."""

import datetime as dt
import uuid
from datetime import UTC

from langgraph.runtime import Runtime
from sqlalchemy import select

from ...models import Conversation, Home, HomeMember, Message, ToolCall, User
from ..agents.base_agent import CopilotContext
from ..agents.state import TurnState
from ..config.settings import LLM
from ..memory import short_term
from ..skills import retrieval
from ..skills.chunker import no_tone
from ..tools import db_connector as db
from ..tools import home_data

YES = {"co", "ok", "dong y", "yes", "duoc", "u", "uh", "vang", "dung roi", "lam di"}
NO = {"khong", "no", "huy", "thoi", "khoi", "dung"}


def _short(text: str) -> str:
    return " ".join(no_tone(text).replace("!", " ").replace(".", " ").split())


async def _pending(s, call_id: str, conversation_id: str) -> ToolCall | None:
    """A write still waiting for its yes, of this conversation, not too old."""
    row = await s.scalar(
        select(ToolCall).join(Message, Message.id == ToolCall.message_id)
        .where(ToolCall.id == uuid.UUID(call_id), ToolCall.ok.is_(None),
               Message.conversation_id == uuid.UUID(conversation_id)))
    limit = dt.timedelta(minutes=LLM["executor"]["pending_minutes"])
    if row is None or dt.datetime.now(UTC) - row.created_at > limit:
        return None
    return row


async def load_context(state: TurnState, runtime: Runtime[CopilotContext]) -> dict:
    ctx, trigger = runtime.context, state["trigger"]
    out: dict = {}
    async with ctx.app()() as s:
        user = member = None
        if trigger in ("schedule", "event"):
            home = await s.get(Home, uuid.UUID(state["home_id"]))
            if home is None:
                raise LookupError(f"home {state['home_id']} not found")
            conv_id, history, last = state.get("conversation_id"), [], None
            if trigger == "event":
                conv = await s.get(Conversation, uuid.UUID(conv_id))
                if conv is None or conv.home_id != home.id:
                    raise LookupError("conversation not found")
                user = await s.get(User, conv.user_id)
        else:
            user = await s.get(User, uuid.UUID(state["user_id"]))
            member = await s.scalar(select(HomeMember).where(
                HomeMember.user_id == uuid.UUID(state["user_id"])))
            if user is None or member is None:
                raise LookupError("this account has no home yet")
            home = await s.get(Home, member.home_id)
            conv_id, history = await short_term.open_conversation(
                s, home.id, user.id, state.get("conversation_id"), state["question"])
            last = await short_term.last_turn(s, conv_id) if state.get("conversation_id") else None
            await s.commit()
            pending_id = state.get("confirm_call_id")
            answer = _short(state["question"])
            if not pending_id and last and last.get("pending") and answer in YES | NO:
                if answer in NO:
                    row = await _pending(s, last["pending"]["id"], conv_id)
                    if row is not None:
                        row.ok = False
                        await s.commit()
                    out["outcome"] = "declined"
                else:
                    pending_id = last["pending"]["id"]
            if pending_id:
                row = await _pending(s, pending_id, conv_id)
                if row is None:
                    out["outcome"] = "expired"
                else:
                    skill = await retrieval.load_skill(s, home_id=str(home.id),
                                                       code=row.input.get("skill"))
                    out.update(trigger="confirm", skill=skill, retrieval="given", plan=[{
                        "id": str(row.id), "tool": row.tool, "args": row.input.get("args", {}),
                        "source": "confirm"}])
        token = await db.issue_scope_token(s, home.id)
        if trigger in ("schedule", "event"):
            skill = await retrieval.load_skill(s, home_id=str(home.id), code=state["skill_code"])
            if skill is None:
                raise LookupError(f"skill {state['skill_code']} not found")
            out.update(skill=skill, retrieval="given")
    async with db.copilot_tx(ctx.copilot(), token) as conn:
        facts = await home_data.home_facts(conn, home.timezone)
        devices = await home_data.device_names(conn)
    return {
        **out,
        "conversation_id": conv_id,
        "user": None if user is None else {
            "id": str(user.id), "name": user.full_name or user.email.split("@")[0],
            "role": member.role if member else None},
        "home": {"id": str(home.id), "name": home.name, "timezone": home.timezone,
                 "tariff_plan": home.tariff_plan_code, "billing_cycle_day": home.billing_cycle_day,
                 "memory_enabled": home.copilot_memory, "devices": devices, **facts},
        "history": history, "last_turn": last, "token": token, "rounds": 0, "failed_rounds": 0,
    }
