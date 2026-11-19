from fastapi import APIRouter

from .home import router as home_router

router = APIRouter(prefix="/homes", tags=["homes"])
router.include_router(home_router)

__all__ = ["router"]
