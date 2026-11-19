from fastapi import APIRouter

from .cohort import router as cohort_router

router = APIRouter(prefix="/insights", tags=["insights"])
router.include_router(cohort_router)

__all__ = ["router"]
