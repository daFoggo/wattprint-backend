from fastapi import APIRouter

router = APIRouter(prefix="/billing", tags=["billing"])

__all__ = ["router"]
