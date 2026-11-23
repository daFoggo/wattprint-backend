from fastapi import APIRouter

from .demo import router as demo_router
from .user import router as user_router

router = APIRouter()
router.include_router(user_router)
router.include_router(demo_router)

__all__ = ["router"]
