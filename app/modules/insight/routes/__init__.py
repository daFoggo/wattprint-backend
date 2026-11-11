from fastapi import APIRouter

router = APIRouter(prefix="/insights", tags=["insights"])

__all__ = ["router"]
