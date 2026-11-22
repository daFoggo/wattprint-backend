import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from app.common.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.dependencies import DbSession
from app.modules.home.api import Membership

from .. import services
from ..schemas import WatchCreate, WatchCreated, WatchRead
from ..utils import WatchError

router = APIRouter()


@router.get("/watches", summary="The alerts the user asked Wappi to watch, active first")
async def watches(member: Membership, db: DbSession) -> list[WatchRead]:
    return [
        WatchRead.model_validate(w)
        for w in await services.list_watches(db, member.user_id, member.home_id)
    ]


@router.post("/watches", status_code=201, summary="Set an alert by hand (Wappi sets the same kind)")
async def create(body: WatchCreate, member: Membership, db: DbSession) -> WatchCreated:
    try:
        w, value = await services.create_watch(
            db, member.user_id, member.home_id, now=datetime.now(UTC), **body.model_dump()
        )
    except WatchError as e:
        error = ConflictError if e.code in ("already_crossed", "too_many") else UnprocessableError
        extra = {"value_now": str(e.value)} if e.value is not None else {}
        raise error(str(e), code=e.code, extra=extra) from e
    await db.commit()
    return WatchCreated.model_validate(
        {**WatchRead.model_validate(w).model_dump(), "value_now": value}
    )


@router.delete("/watches/{watch_id}", status_code=204, summary="Stop watching (its owner only)")
async def cancel(watch_id: uuid.UUID, member: Membership, db: DbSession) -> None:
    if not await services.cancel_watch(db, member.user_id, member.home_id, watch_id):
        raise NotFoundError("No such watch of yours", code="watch_not_found")
    await db.commit()
