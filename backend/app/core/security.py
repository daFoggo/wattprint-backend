"""Session validation against the Better Auth service.

The Expo client sends the Better Auth cookie (authClient.getCookie()) or a
bearer token. Both headers are forwarded to the get-session endpoint.
"""

from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core.config import settings


class AuthUser(BaseModel):
    id: str
    email: str
    name: str | None = None
    email_verified: bool = False


async def get_current_user(request: Request) -> AuthUser:
    headers = {k: v for k in ("cookie", "authorization") if (v := request.headers.get(k))}
    if not headers:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    url = f"{settings.auth_service_url}{settings.auth_base_path}/get-session"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Auth service unavailable"
        ) from exc
    data = resp.json() if resp.status_code == 200 and resp.content else None
    if not data or not data.get("user"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    u = data["user"]
    return AuthUser(
        id=u["id"],
        email=u["email"],
        name=u.get("name"),
        email_verified=u.get("emailVerified", False),
    )


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
