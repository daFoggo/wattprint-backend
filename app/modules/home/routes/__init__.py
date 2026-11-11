from fastapi import APIRouter

router = APIRouter(prefix="/homes", tags=["homes"])

__all__ = ["router"]
