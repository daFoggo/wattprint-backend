from fastapi import APIRouter

from .dashboard import router as dashboard_router
from .devices import router as devices_router
from .weather import router as weather_router

router = APIRouter(prefix="/energy", tags=["energy"])
router.include_router(dashboard_router)
router.include_router(devices_router)
router.include_router(weather_router)

__all__ = ["router"]
