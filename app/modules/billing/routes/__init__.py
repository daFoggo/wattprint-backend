from fastapi import APIRouter

from .bill import router as bill_router

router = APIRouter(prefix="/billing", tags=["billing"])
router.include_router(bill_router)

__all__ = ["router"]
