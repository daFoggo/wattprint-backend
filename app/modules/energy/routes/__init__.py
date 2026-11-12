from fastapi import APIRouter

from .dashboard import router as dashboard_router

router = APIRouter(prefix="/energy", tags=["energy"])
router.include_router(dashboard_router)

__all__ = ["router"]
