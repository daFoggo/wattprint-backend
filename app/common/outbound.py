import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

import httpx
from fastapi import status
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal

from .exceptions import AppError

# Every call that leaves WattPrint goes through here: require consent (when the purpose needs
# it), record one row in tb_outbound_log (never the content), then send with client(party).
# External addresses live only in app/config.py and in this file (tests/test_outbound.py).

CONSENT_VERSION = "2026-11-28"  # change it with the wording: everyone is asked again
PURPOSES = ("wappi", "voice", "email")


def base_url(party: str) -> str:
    return {
        "openrouter": settings.openrouter_base_url,
        "astralx": settings.astralx_base_url,
        "openweather": settings.openweather_base_url,
        "telegram": settings.telegram_api_url,
        "text2sql": settings.text2sql_url,  # ours, but it hands the question on to OpenRouter
    }[party]


def client(party: str, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url(party), **kwargs)


class ConsentRequiredError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "consent_required"
    message = "This needs your consent first"


@dataclass
class Scope:
    user_id: uuid.UUID | None
    home_id: uuid.UUID | None
    detail: str | None = None
    sent: list[dict] = field(default_factory=list)  # what this request sent out, for the reply


_scope: ContextVar[Scope | None] = ContextVar("outbound_scope", default=None)


@contextmanager
def scope(user_id=None, home_id=None, detail: str | None = None) -> Iterator[Scope]:
    """Who the calls inside are for; record() reads it and collects what was sent."""
    s = Scope(user_id, home_id, detail)
    token = _scope.set(s)
    try:
        yield s
    finally:
        _scope.reset(token)


def summary(s: Scope) -> dict:
    """What one answer sent out, for its "Sent outside" line: who to, which data, how fine."""
    parties = list(dict.fromkeys(x["party"] for x in s.sent))
    data = list(dict.fromkeys(d for x in s.sent for d in x["data"]))
    return {"parties": parties, "data": data, "detail": s.detail}


def consented_sql(user_col: str, purpose: str) -> str:
    """A WHERE condition: the user's latest choice for `purpose` is yes, on the current wording.
    TRUE while consent is not enforced (see settings.consent_enforced)."""
    if not settings.consent_enforced:
        return "TRUE"
    assert purpose in PURPOSES
    return (
        f"(SELECT c.granted AND c.version = '{CONSENT_VERSION}' FROM public.tb_consent c "
        f"WHERE c.user_id = {user_col} AND c.purpose = '{purpose}' "
        "ORDER BY c.created_at DESC, c.id DESC LIMIT 1) IS TRUE"
    )


async def granted(user_id: uuid.UUID, purpose: str) -> bool:
    """The latest choice for this purpose, and only if it was made on the current wording."""
    async with SessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT granted, version FROM public.tb_consent "
                    "WHERE user_id = :u AND purpose = :p ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"u": user_id, "p": purpose},
            )
        ).first()
    return bool(row and row.granted and row.version == CONSENT_VERSION)


async def require(user_id: uuid.UUID, purpose: str) -> None:
    if settings.consent_enforced and not await granted(user_id, purpose):
        raise ConsentRequiredError(extra={"purpose": purpose})


async def record(
    party: str,
    purpose: str,
    data: list[str],
    detail: str | None = None,
    *,
    user_id: uuid.UUID | None = None,
    home_id: uuid.UUID | None = None,
) -> None:
    """One row per call, before it is sent: who to, why, which kinds of data, how fine."""
    s = _scope.get()
    if s:
        user_id, home_id, detail = user_id or s.user_id, home_id or s.home_id, detail or s.detail
        s.sent.append({"party": party, "purpose": purpose, "data": data, "detail": detail})
    async with SessionLocal() as db, db.begin():
        await db.execute(
            text(
                "INSERT INTO public.tb_outbound_log (user_id, home_id, party, purpose, data, "
                "detail) VALUES (:u, :h, :party, :purpose, :data, :detail)"
            ),
            {
                "u": user_id,
                "h": home_id,
                "party": party,
                "purpose": purpose,
                "data": data,
                "detail": detail,
            },
        )


async def recent(user_id: uuid.UUID, days: int = 30) -> list[dict]:
    """What left WattPrint for this person, and for their home with no person named (weather)."""
    async with SessionLocal() as s:
        rows = await s.execute(
            text(
                "SELECT created_at, party, purpose, data, detail FROM public.tb_outbound_log l "
                "WHERE l.created_at > now() - make_interval(days => :d) AND (l.user_id = :u OR "
                "(l.user_id IS NULL AND l.home_id IN (SELECT home_id FROM public.tb_home_member "
                "WHERE user_id = :u))) ORDER BY l.created_at DESC LIMIT 500"
            ),
            {"u": user_id, "d": days},
        )
        return [dict(r._mapping) for r in rows]


async def prune(days: int = 90) -> None:
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "DELETE FROM public.tb_outbound_log "
                "WHERE created_at < now() - make_interval(days => :d)"
            ),
            {"d": days},
        )
