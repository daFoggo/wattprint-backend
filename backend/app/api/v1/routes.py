from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)


@router.get("/health", tags=["system"], summary="Liveness + DB check")
async def health(db: DbSession) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
