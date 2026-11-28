import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.common.exceptions import UnprocessableError
from app.database import SessionLocal
from app.dependencies import DbSession
from app.modules.home.api import DetailedMembership, HomeMember, Membership

from .. import services
from ..schemas import Overview, Power, SeriesPoint, Today

router = APIRouter()

STREAM_POLL_S = 3
STREAM_PING_EVERY = 5  # polls between keep-alive comments (15 s)
STREAM_BACKLOG = timedelta(minutes=5)  # sent on connect, so the live chart starts full
STREAM_MAX = timedelta(minutes=10)  # auth is checked on connect; EventSource reconnects through it


@router.get("/overview", summary="Live power and today's energy of the user's home")
async def overview(member: Membership, db: DbSession) -> Overview:
    now = datetime.now(UTC)
    home_id = member.home_id
    # The day's total is for everyone; the moment's power is not for a daily member.
    live = None if member.detail == "daily" else await services.latest_reading(db, home_id, now)
    today = await services.today_energy(db, home_id, now)
    return Overview(
        live=Power.model_validate(live) if live else None,
        today=Today.model_validate(today) if today else None,
    )


@router.get("/series", summary="Main-meter power series, at most ~max_points points")
async def series(
    member: Membership,
    db: DbSession,
    since: datetime,
    until: datetime,
    max_points: Annotated[int, Query(ge=1, le=2000)] = 600,
) -> list[SeriesPoint]:
    daily = member.detail == "daily"  # a daily member gets day buckets, never finer
    try:
        points = await services.meter_series(
            db, member.home_id, since, until, max_points, daily=daily
        )
    except ValueError as exc:  # naive datetimes, empty or > 90 day window
        raise UnprocessableError(str(exc)) from None
    return [SeriesPoint.model_validate(p) for p in points]


@router.get(
    "/stream",
    summary=(
        "Server-sent events: `reading` for each main-meter sample (the last 5 minutes first), "
        "`nilm.updated` when the device estimates move on (data: `analyzed_until`)"
    ),
)
async def stream(request: Request, member: DetailedMembership, db: DbSession) -> StreamingResponse:
    home_id, user_id = member.home_id, member.user_id
    # Release the auth session's pooled connection now: the stream lives for minutes.
    await db.close()

    async def events():
        opened = datetime.now(UTC)
        last = opened - STREAM_BACKLOG
        idle = 0
        async with SessionLocal() as session:
            analyzed = await services.analyzed_until(session, home_id)
        while datetime.now(UTC) - opened < STREAM_MAX and not await request.is_disconnected():
            # shortcut: one poll per open stream every 3 s; use LISTEN/NOTIFY when many watch.
            async with SessionLocal() as session:
                # Removed or cut to daily while the stream is open: it ends.
                now_member = await session.get(HomeMember, (home_id, user_id))
                if now_member is None or now_member.detail == "daily":
                    return
                samples = await services.main_readings(session, home_id, last)
                newest = await services.analyzed_until(session, home_id)
            if newest is not None and (analyzed is None or newest > analyzed):
                analyzed = newest
                yield f'event: nilm.updated\ndata: {{"analyzed_until": "{newest.isoformat()}"}}\n\n'
            if samples:
                last, idle = samples[-1].ts, 0
                for sample in samples:
                    data = Power.model_validate(sample).model_dump_json()
                    yield f"event: reading\ndata: {data}\n\n"
            else:
                idle += 1
                if idle % STREAM_PING_EVERY == 0:
                    yield ": ping\n\n"
            await asyncio.sleep(STREAM_POLL_S)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
