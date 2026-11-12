import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.common.exceptions import UnprocessableError
from app.database import SessionLocal
from app.dependencies import DbSession

from .. import services
from ..dependencies import CurrentHome
from ..schemas import Overview, Power, SeriesPoint, Today

router = APIRouter()

STREAM_POLL_S = 3
STREAM_PING_EVERY = 5  # polls between keep-alive comments (15 s)
STREAM_BACKLOG = timedelta(minutes=5)  # sent on connect, so the live chart starts full
STREAM_MAX = timedelta(minutes=10)  # auth is checked on connect; EventSource reconnects through it


@router.get("/overview", summary="Live power and today's energy of the user's home")
async def overview(home_id: CurrentHome, db: DbSession) -> Overview:
    now = datetime.now(UTC)
    live = await services.latest_reading(db, home_id, now)
    today = await services.today_energy(db, home_id, now)
    return Overview(
        live=Power.model_validate(live) if live else None,
        today=Today.model_validate(today) if today else None,
    )


@router.get("/series", summary="Main-meter power series, at most ~max_points points")
async def series(
    home_id: CurrentHome,
    db: DbSession,
    since: datetime,
    until: datetime,
    max_points: Annotated[int, Query(ge=1, le=2000)] = 600,
) -> list[SeriesPoint]:
    try:
        points = await services.meter_series(db, home_id, since, until, max_points)
    except ValueError as exc:  # naive datetimes, empty or > 90 day window
        raise UnprocessableError(str(exc)) from None
    return [SeriesPoint.model_validate(p) for p in points]


@router.get(
    "/stream",
    summary="Server-sent events: `reading` for each main-meter sample, the last 5 minutes first",
)
async def stream(request: Request, home_id: CurrentHome, db: DbSession) -> StreamingResponse:
    # Release the auth session's pooled connection now: the stream lives for minutes.
    await db.close()

    async def events():
        opened = datetime.now(UTC)
        last = opened - STREAM_BACKLOG
        idle = 0
        while datetime.now(UTC) - opened < STREAM_MAX and not await request.is_disconnected():
            # shortcut: one poll per open stream every 3 s; use LISTEN/NOTIFY when many watch.
            async with SessionLocal() as session:
                samples = await services.main_readings(session, home_id, last)
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
