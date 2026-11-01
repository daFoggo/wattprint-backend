from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.security import AuthUser, CurrentUser
from app.modules.disaggregation.router import router as disaggregation_router

router = APIRouter()
router.include_router(disaggregation_router)


@router.get("/health", tags=["system"], summary="Liveness + DB check")
async def health(db: DbSession) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/me", tags=["auth"], summary="Current Better Auth user")
async def me(user: CurrentUser) -> AuthUser:
    return user
