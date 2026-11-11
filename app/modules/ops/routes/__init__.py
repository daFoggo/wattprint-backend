from fastapi import APIRouter

router = APIRouter(prefix="/ops", tags=["ops"])

__all__ = ["router"]
