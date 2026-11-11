from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .common.exceptions import register_exception_handlers
from .config import settings
from .modules.auth.routes import router as auth_router
from .modules.billing.routes import router as billing_router
from .modules.energy.routes import router as energy_router
from .modules.home.routes import router as home_router
from .modules.insight.routes import router as insight_router
from .modules.ops.routes import router as ops_router
from .routers import health

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    openapi_tags=[
        {"name": "system", "description": "Health and diagnostics"},
        {"name": "users", "description": "User profile"},
    ],
)

register_exception_handlers(app)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

for router in (
    health.router,
    auth_router,
    home_router,
    energy_router,
    billing_router,
    insight_router,
    ops_router,
):
    app.include_router(router, prefix="/api/v1")
