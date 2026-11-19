from fastapi import APIRouter

from .copilot import router as copilot_router

router = APIRouter(prefix="/copilot", tags=["copilot"])
router.include_router(copilot_router)

__all__ = ["router"]
