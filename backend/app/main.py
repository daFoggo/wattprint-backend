from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import auth, health, users

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    openapi_tags=[
        {"name": "system", "description": "Health and diagnostics"},
        {"name": "auth", "description": "Register, login, token refresh"},
        {"name": "users", "description": "User profile"},
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

for module in (health, auth, users):
    app.include_router(module.router, prefix="/api/v1")
