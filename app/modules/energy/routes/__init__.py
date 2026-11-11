from fastapi import APIRouter

router = APIRouter(prefix="/energy", tags=["energy"])

__all__ = ["router"]
