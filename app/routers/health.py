from fastapi import APIRouter
from sqlalchemy import text

from ..dependencies import DbSession

router = APIRouter(prefix="/health", tags=["system"])


@router.get("", summary="Liveness + DB check")
async def health(db: DbSession) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
