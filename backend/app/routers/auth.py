from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from ..dependencies import DbSession
from ..schemas import RefreshRequest, TokenPair, UserCreate, UserRead
from ..services import auth as service

router = APIRouter(prefix="/auth", tags=["auth"])

_BEARER = {"WWW-Authenticate": "Bearer"}


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="Create an account")
async def register(data: UserCreate, db: DbSession) -> UserRead:
    user = await service.register_user(db, data)
    if user is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    return UserRead.model_validate(user)


@router.post("/token", summary="Log in (OAuth2 password flow, username is the email)")
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> TokenPair:
    user = await service.authenticate(db, form.username, form.password)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password", headers=_BEARER
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Inactive user")
    return await service.issue_tokens(db, user)


@router.post("/refresh", summary="Rotate the refresh token")
async def refresh(body: RefreshRequest, db: DbSession) -> TokenPair:
    pair = await service.rotate_refresh_token(db, body.refresh_token)
    if pair is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token", headers=_BEARER)
    return pair


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a refresh token")
async def logout(body: RefreshRequest, db: DbSession) -> Response:
    await service.revoke_refresh_token(db, body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
