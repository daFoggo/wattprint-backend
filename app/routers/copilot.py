"""/api/v1/copilot: ask (JSON or SSE), conversations, terms, rules, suggestions."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..copilot.agents.base_agent import CopilotContext
from ..copilot.agents.router import copilot_graph
from ..copilot.nodes.ingress_node import RejectedError
from ..copilot.skills import advice as copilot_advice
from ..copilot.skills import rules as copilot_rules
from ..copilot.tools import db_connector as copilot_db
from ..dependencies import CurrentUser, DbSession
from ..models import (
    Conversation,
    Device,
    DeviceType,
    Home,
    HomeMember,
    Message,
    Rule,
    SavingsMeasure,
    Suggestion,
    SuggestionFeedback,
    Term,
    ToolCall,
)
from ..schemas.copilot import (
    AskIn,
    AskOut,
    ChatMessageOut,
    ConversationOut,
    FeedbackIn,
    RefreshOut,
    RuleIn,
    RuleOut,
    RulePatch,
    SuggestionOut,
    TermIn,
    TermOut,
    TermPatch,
)
from .common import require_home

router = APIRouter(prefix="/copilot", tags=["copilot"])


def get_copilot_context() -> CopilotContext:
    """The graphs' runtime context; 503 while the Copilot is not configured."""
    if not settings.copilot_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The Copilot is off: set OPENROUTER_API_KEY, OPENROUTER_MODEL and "
            "COPILOT_DATABASE_URL",
        )
    return CopilotContext()


Context = Annotated[CopilotContext, Depends(get_copilot_context)]


# --- ask ---


_ADDITIVE = ("steps", "queries", "results", "facts", "timings", "flags")


def _merge(state: dict, update: dict | None) -> None:
    for key, value in (update or {}).items():
        state[key] = [*state.get(key, []), *value] if key in _ADDITIVE else value


def ask_out(state: dict[str, Any]) -> AskOut:
    api = state.get("api") or {}
    facts = [f.model_dump() for f in state.get("facts") or []]
    suggestions = api.get("suggestions")
    top = max(suggestions, key=lambda g: g.get("expected_amount") or 0) if suggestions else None
    card = state.get("card")
    skill = state.get("skill")
    return AskOut(
        conversation_id=state["conversation_id"], message_id=state["message_id"],
        answer=state.get("answer", ""), facts=facts,
        assumptions=[a for r in state.get("results", []) for a in r.get("assumptions", [])],
        steps=state.get("steps", []), result=api.get("result"), cost=api.get("cost"),
        clarification=({k: v for k, v in card.items() if k != "kind"}
                       if card and card["kind"] == "clarification" else None),
        confirm=card if card and card["kind"] == "confirm" else None,
        suggestions=suggestions,
        skill={"code": skill["code"], "name": skill["name"], "mode": skill["mode"],
               "household": skill.get("household", False)} if skill else None,
        retrieval={"case": state.get("retrieval"), "standalone": state.get("standalone"),
                   "rewrite": (state.get("rewrite") or {}).get("method"),
                   "candidates": [{"code": c["code"], "sim": c["sim"]}
                                  for c in state.get("candidates", [])]},
        tools=[{"tool": r["tool"], "args": r.get("args", {}), "ok": r["ok"], "ms": r["ms"],
                "error": r.get("error")} for r in state.get("results", [])],
        timings=state.get("timings", []), followups=state.get("followups", []),
        memory=[{"summary": m["summary"], "ended_at": m["ended_at"]}
                for m in (state.get("memory") or {}).get("sessions", [])],
        message=ChatMessageOut(
            id=state["message_id"], who="ai", text=state.get("answer", ""), facts=facts,
            cta=top["title"] if top else None, cta_desc=top["body"] if top else None,
        ),
    )


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _stream(inp: dict, ctx: CopilotContext) -> AsyncIterator[str]:
    state: dict[str, Any] = dict(inp)
    try:
        async for mode, chunk in copilot_graph.astream(inp, context=ctx,
                                                       stream_mode=["updates", "messages"]):
            if mode == "messages":
                msg, meta = chunk
                if (meta.get("langgraph_node") == "generate_answer"
                        and getattr(msg, "content", None)):
                    yield _sse("token", {"text": msg.content})
                continue
            for node, update in chunk.items():
                _merge(state, update)
                yield _sse("step", {"node": node})
                if node == "act" and (state.get("api") or {}).get("result"):
                    result = state["api"]["result"]
                    yield _sse("result", {"rows": result["rows"], "sql": result["sql"]})
                if node == "act" and state.get("card"):
                    yield _sse("card", state["card"])
        yield _sse("done", ask_out(state).model_dump(mode="json"))
    except (LookupError, RejectedError) as exc:
        yield _sse("error", {"detail": str(exc)})


@router.post("/ask", response_model=AskOut)
async def ask(body: AskIn, request: Request, user: CurrentUser, db: DbSession, ctx: Context):
    """Ask about this home's electricity. `Accept: text/event-stream` streams step / token /
    result / clarification / done events."""
    await require_home(db, user)
    inp = {"trigger": "chat", "question": body.question, "user_id": str(user.id),
           "conversation_id": str(body.conversation_id) if body.conversation_id else None,
           "confirm_call_id": str(body.confirm_call_id) if body.confirm_call_id else None}
    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(_stream(inp, ctx), media_type="text/event-stream")
    try:
        state = await copilot_graph.ainvoke(inp, context=ctx)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except RejectedError as exc:
        raise HTTPException(exc.status, exc.detail) from None
    return ask_out(state)


# --- conversations ---


@router.get("/conversations", response_model=list[ConversationOut])
async def conversations(user: CurrentUser, db: DbSession):
    home_id = await require_home(db, user)
    last = (
        select(Message.conversation_id, func.max(Message.created_at).label("at"))
        .group_by(Message.conversation_id).subquery()
    )
    updated = func.coalesce(last.c.at, Conversation.created_at)
    rows = await db.execute(
        select(Conversation, updated.label("updated_at"))
        .outerjoin(last, last.c.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id, Conversation.home_id == home_id)
        .order_by(updated.desc())
    )
    return [ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=at)
            for c, at in rows]


@router.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessageOut])
async def messages(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession):
    home_id = await require_home(db, user)
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id or conv.home_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    msgs = (await db.execute(
        select(Message).where(Message.conversation_id == conversation_id,
                              Message.role.in_(("user", "assistant")))
        .order_by(Message.created_at)
    )).scalars().all()
    facts: dict[uuid.UUID, list] = {}
    for message_id, inp in await db.execute(
        select(ToolCall.message_id, ToolCall.input)
        .where(ToolCall.message_id.in_([m.id for m in msgs]))
    ):
        if inp.get("facts") and message_id not in facts:
            facts[message_id] = inp["facts"]
    return [ChatMessageOut(id=str(m.id), who="me" if m.role == "user" else "ai", text=m.content,
                           facts=facts.get(m.id, []), created_at=m.created_at) for m in msgs]


# --- terms ---


def _unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


async def _check_target(db, home_id: uuid.UUID, kind: str, target: dict) -> dict:
    if kind == "device":
        try:
            device = await db.get(Device, uuid.UUID(str(target.get("device_id"))))
        except ValueError:
            device = None
        if device is None or device.home_id != home_id or device.deleted_at is not None:
            raise _unprocessable("target.device_id is not a device of your home")
        return {"device_id": str(device.id)}
    if kind == "device_type":
        if await db.get(DeviceType, str(target.get("code"))) is None:
            raise _unprocessable("target.code is not a device type")
        return {"code": target["code"]}
    if kind == "time_window":
        a, b = target.get("start_hour"), target.get("end_hour")
        if not (isinstance(a, int) and isinstance(b, int) and 0 <= a < 24 and 0 < b <= 24):
            raise _unprocessable("target needs start_hour 0..23 and end_hour 1..24")
        return {"start_hour": a, "end_hour": b}
    measure, op, value = target.get("measure"), target.get("op"), target.get("value")
    if (measure not in ("energy", "average_power", "peak_power")
            or op not in (">", "<", ">=", "<=") or not isinstance(value, int | float)):
        raise _unprocessable("target needs measure (energy|average_power|peak_power), op and "
                             "a number value")
    return {"measure": measure, "op": op, "value": value}


async def _match_key(db, phrase: str) -> str:
    key = await db.scalar(text("SELECT copilot_ro.match_key(:p)"), {"p": phrase})
    if not key:
        raise _unprocessable("the phrase has no word left to match on")
    return key


@router.get("/terms", response_model=list[TermOut])
async def list_terms(user: CurrentUser, db: DbSession):
    home_id = await require_home(db, user)
    return (await db.execute(
        select(Term).where(Term.home_id == home_id).order_by(Term.phrase)
    )).scalars().all()


@router.post("/terms", response_model=TermOut, status_code=status.HTTP_201_CREATED)
async def save_term(body: TermIn, user: CurrentUser, db: DbSession):
    """Save (or redefine) a word of this home, e.g. the choice on a clarification card."""
    home_id = await require_home(db, user)
    target = await _check_target(db, home_id, body.kind, body.target)
    key = await _match_key(db, body.phrase)
    if body.created_from_message_id is not None:
        owner = await db.scalar(
            select(Conversation.id).join(Message, Message.conversation_id == Conversation.id)
            .where(Message.id == body.created_from_message_id,
                   Conversation.home_id == home_id, Conversation.user_id == user.id)
        )
        if owner is None:
            raise _unprocessable("created_from_message_id is not a message of yours")
    stmt = insert(Term).values(
        home_id=home_id, phrase=body.phrase, match_key=key, kind=body.kind, target=target,
        created_by=user.id, created_from_message_id=body.created_from_message_id,
    )
    term_id = await db.scalar(
        stmt.on_conflict_do_update(
            constraint="uq_term_home_id",
            set_={"phrase": stmt.excluded.phrase, "kind": stmt.excluded.kind,
                  "target": stmt.excluded.target, "updated_at": func.now()},
        ).returning(Term.id)
    )
    await db.commit()
    return await db.get(Term, term_id, populate_existing=True)


async def _own_term(db, user, term_id: uuid.UUID) -> Term:
    home_id = await require_home(db, user)
    term = await db.get(Term, term_id)
    if term is None or term.home_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "term not found")
    return term


@router.patch("/terms/{term_id}", response_model=TermOut)
async def patch_term(term_id: uuid.UUID, body: TermPatch, user: CurrentUser, db: DbSession):
    term = await _own_term(db, user, term_id)
    if body.phrase is not None:
        term.phrase, term.match_key = body.phrase, await _match_key(db, body.phrase)
    if body.target is not None:
        term.target = await _check_target(db, term.home_id, term.kind, body.target)
    await db.commit()
    return term


@router.delete("/terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_term(term_id: uuid.UUID, user: CurrentUser, db: DbSession):
    await db.delete(await _own_term(db, user, term_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- rules ---


def _rule_out(rule: Rule, hits: int | None = None) -> RuleOut:
    return RuleOut(id=rule.id, name=rule.name, motif=rule.motif, body=rule.body,
                   suggest_kind=rule.suggest_kind, enabled=rule.enabled, version=rule.version,
                   shared=rule.home_id is None, dry_run_hits=hits)


async def _owner_home(db, user) -> uuid.UUID:
    home_id = await require_home(db, user)
    role = await db.scalar(select(HomeMember.role).where(HomeMember.user_id == user.id))
    if role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the home's owner can change rules")
    return home_id


async def _compile_and_dry_run(db, home_id: uuid.UUID, body: dict, ctx: CopilotContext):
    try:
        rule = copilot_rules.validate(body)
        compiled = copilot_rules.compile_rule(rule)
    except (copilot_rules.RuleError, ValueError) as exc:
        raise _unprocessable(str(exc)) from None
    home = await db.get(Home, home_id)
    token = await copilot_db.issue_scope_token(db, home_id)
    async with copilot_db.copilot_tx(ctx.copilot(), token) as conn:
        hits = await copilot_rules.dry_run(conn, rule, ctx.local_today(), home.timezone)
    return rule, compiled, hits


@router.get("/rules", response_model=list[RuleOut])
async def list_rules(user: CurrentUser, db: DbSession):
    home_id = await require_home(db, user)
    found = (await db.execute(
        select(Rule).where((Rule.home_id.is_(None)) | (Rule.home_id == home_id))
        .order_by(Rule.home_id.nulls_first(), Rule.name)
    )).scalars().all()
    return [_rule_out(r) for r in found]


@router.post("/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(body: RuleIn, user: CurrentUser, db: DbSession, ctx: Context):
    """Add a household rule (owner only). It is checked, compiled and dry-run on the last
    7 days; the response says how many times it would have fired."""
    home_id = await _owner_home(db, user)
    rule, compiled, hits = await _compile_and_dry_run(db, home_id, body.body, ctx)
    row = Rule(home_id=home_id, name=body.name, motif=rule.motif,
               body=rule.model_dump(mode="json"), suggest_kind=rule.then.suggest,
               compiled_sql=compiled, enabled=body.enabled,
               content_hash=copilot_rules.content_hash(rule), created_by=user.id)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:  # unique (home, name)
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "a rule with this name exists") from None
    return _rule_out(row, hits)


async def _own_rule(db, user, rule_id: uuid.UUID) -> Rule:
    home_id = await _owner_home(db, user)
    rule = await db.get(Rule, rule_id)
    if rule is None or rule.home_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rule not found (shared rules are "
                            "changed in the code)")
    return rule


@router.patch("/rules/{rule_id}", response_model=RuleOut)
async def patch_rule(rule_id: uuid.UUID, body: RulePatch, user: CurrentUser, db: DbSession,
                     ctx: Context):
    row = await _own_rule(db, user, rule_id)
    hits = None
    if body.body is not None:
        rule, compiled, hits = await _compile_and_dry_run(db, row.home_id, body.body, ctx)
        row.body, row.motif, row.suggest_kind = (rule.model_dump(mode="json"), rule.motif,
                                                 rule.then.suggest)
        row.compiled_sql, row.content_hash = compiled, copilot_rules.content_hash(rule)
        row.version += 1
    if body.name is not None:
        row.name = body.name
    if body.enabled is not None:
        row.enabled = body.enabled
    await db.commit()
    return _rule_out(row, hits)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, user: CurrentUser, db: DbSession):
    await db.delete(await _own_rule(db, user, rule_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- suggestions ---

OPEN = ("proposed", "shown")


async def _suggestions(db, home_id: uuid.UUID, ids: list[uuid.UUID] | None = None,
                       open_only: bool = True) -> list[SuggestionOut]:
    q = (select(Suggestion, Device.name, SavingsMeasure)
         .outerjoin(Device, Device.id == Suggestion.device_id)
         .outerjoin(SavingsMeasure, SavingsMeasure.suggestion_id == Suggestion.id)
         .where(Suggestion.home_id == home_id))
    if ids is not None:
        q = q.where(Suggestion.id.in_(ids))
    elif open_only:
        q = q.where(Suggestion.status.in_(OPEN))
    rows = await db.execute(q.order_by(Suggestion.expected_amount.desc().nulls_last()))
    def saving(m: SavingsMeasure | None) -> dict | None:
        if m is None:
            return None
        return {"baseline_kwh": float(m.baseline_kwh), "actual_kwh": float(m.actual_kwh),
                "saved_kwh": round(float(m.baseline_kwh - m.actual_kwh), 3), "method": m.method,
                "measured_at": m.measured_at}

    return [SuggestionOut(id=g.id, kind=g.kind, title=g.title, body=g.body, device=name,
                          expected_kwh=g.expected_kwh, expected_amount=g.expected_amount,
                          status=g.status, evidence=g.evidence, created_at=g.created_at,
                          measured_saving=saving(m))
            for g, name, m in rows]


@router.get("/suggestions", response_model=list[SuggestionOut])
async def list_suggestions(
    user: CurrentUser, db: DbSession,
    status_: Annotated[Literal["open", "all"], Query(alias="status")] = "open",
):
    home_id = await require_home(db, user)
    return await _suggestions(db, home_id, open_only=status_ == "open")


@router.post("/suggestions/{suggestion_id}/feedback", response_model=SuggestionOut)
async def feedback(suggestion_id: uuid.UUID, body: FeedbackIn, user: CurrentUser,
                   db: DbSession):
    home_id = await require_home(db, user)
    g = await db.get(Suggestion, suggestion_id)
    if g is None or g.home_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "suggestion not found")
    action, new_status = copilot_advice.FEEDBACK[body.action]
    db.add(SuggestionFeedback(suggestion_id=g.id, user_id=user.id, action=action,
                              note=body.note))
    g.status = new_status
    await db.commit()
    return (await _suggestions(db, home_id, ids=[g.id]))[0]


@router.post("/suggestions/refresh", response_model=RefreshOut)
async def refresh(user: CurrentUser, db: DbSession, ctx: Context):
    """Run the daily_advice skill (its pipeline) for this home now."""
    home_id = await require_home(db, user)
    state = await copilot_graph.ainvoke({"trigger": "schedule", "home_id": str(home_id),
                                         "skill_code": "daily_advice"}, context=ctx)
    stored = [uuid.UUID(i) for i in
              (state.get("tool_data") or {}).get("store_suggestions", {}).get("stored", [])]
    return RefreshOut(stored=len(stored), suggestions=await _suggestions(db, home_id, stored))
