from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import router as v1_router
from app.core.config import settings

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    openapi_tags=[
        {"name": "system", "description": "Health and diagnostics"},
        {"name": "auth", "description": "Identity (sessions issued by Better Auth)"},
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

app.include_router(v1_router, prefix="/api/v1")
