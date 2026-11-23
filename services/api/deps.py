"""FastAPI dependencies: settings, database session, Redis, HTTP client, current user."""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from crew.auth.mailer import Mailer
from crew.auth.tokens import decode_access_token
from crew.config import Settings
from crew.errors import unauthorized
from crew.models import User

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_http(request: Request) -> httpx.AsyncClient:
    http: httpx.AsyncClient = request.app.state.http
    return http


def get_mailer(request: Request) -> Mailer:
    mailer: Mailer = request.app.state.mailer
    return mailer


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Service functions commit their own work."""
    async with request.app.state.session_factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RedisDep = Annotated[Redis, Depends(get_redis)]
HttpDep = Annotated[httpx.AsyncClient, Depends(get_http)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise unauthorized("not_authenticated", "Sign in to continue.")
    user_id = decode_access_token(credentials.credentials, settings)
    user = await session.get(User, user_id)
    if user is None:
        raise unauthorized("invalid_token", "Invalid access token.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
