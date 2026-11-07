import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import auth, copilot, copilot_skills, disaggregation, health, simulations, users

log = logging.getLogger(__name__)


async def _warm_embedder() -> None:
    """Load bge-m3 now, not on the first question (about 8 s on CPU)."""
    try:
        from .copilot.tools.embedder import default_embedder

        await default_embedder().embed_query("khởi động")
    except Exception:  # no cpu/gpu extra installed: the Copilot fails on its first question
        log.exception("copilot embedder warm-up failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    warm = asyncio.create_task(_warm_embedder()) if settings.copilot_enabled else None
    yield
    if warm is not None:
        warm.cancel()


app = FastAPI(
    lifespan=lifespan,
    title=settings.project_name,
    version=settings.version,
    openapi_tags=[
        {"name": "system", "description": "Health and diagnostics"},
        {"name": "auth", "description": "Register, login, token refresh"},
        {"name": "users", "description": "User profile"},
        {"name": "simulations", "description": "Replay a REFIT day through the NILM model"},
        {"name": "disaggregation", "description": "Per-appliance energy from the NILM estimates"},
        {"name": "copilot", "description": "Ask about your energy, words, rules and advice"},
    ],
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

for module in (health, auth, users, simulations, disaggregation, copilot, copilot_skills):
    app.include_router(module.router, prefix="/api/v1")
