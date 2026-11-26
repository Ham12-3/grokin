"""Sign-in routes and `/me`. Logic lives in `crew.auth.service`."""

import html
from typing import Annotated

from fastapi import APIRouter, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from api.deps import CurrentUser, HttpDep, MailerDep, RedisDep, SessionDep, SettingsDep
from crew.auth import service
from crew.errors import AppError
from crew.schemas.auth import (
    EmailStartRequest,
    EmailStartResponse,
    ExchangeRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
    UserOut,
)
from crew.usage import usage_today

router = APIRouter(tags=["auth"])

_CHALLENGE = Query(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

_OPEN_APP_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0;url={link}">
<title>Opening Crew</title>
<style>
body{{font-family:system-ui,sans-serif;display:grid;place-items:center;height:100vh;margin:0;
background:#fafafa;color:#171717}}
main{{text-align:center;max-width:22rem;padding:1rem}}
a{{display:inline-block;margin-top:1rem;padding:.6rem 1.2rem;border-radius:.5rem;
background:#171717;color:#fff;text-decoration:none}}
p{{color:#525252}}
</style>
</head>
<body>
<main>
<h1>You are signed in</h1>
<p>Crew should open now. If it does not, use the button. You can close this tab afterwards.</p>
<a href="{link}">Open Crew</a>
</main>
</body>
</html>
"""


def _open_app_page(deep_link: str, code: str) -> HTMLResponse:
    link = html.escape(f"{deep_link}?code={code}", quote=True)
    return HTMLResponse(
        _OPEN_APP_PAGE.format(link=link),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


@router.post("/auth/email/start", response_model=EmailStartResponse)
async def email_start(
    body: EmailStartRequest, redis: RedisDep, settings: SettingsDep, mailer: MailerDep
) -> EmailStartResponse:
    await service.start_email_login(
        redis, settings, mailer, email=body.email, code_challenge=body.code_challenge
    )
    return EmailStartResponse()


@router.get("/auth/google/start", response_class=RedirectResponse, status_code=302)
async def google_start(
    redis: RedisDep,
    settings: SettingsDep,
    redirect: Annotated[str, Query(max_length=200)],
    code_challenge: Annotated[str, _CHALLENGE],
) -> RedirectResponse:
    url = await service.start_google_login(
        redis, settings, redirect=redirect, code_challenge=code_challenge
    )
    return RedirectResponse(url, status_code=302)


@router.get("/auth/callback", response_class=HTMLResponse)
async def callback(
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    http: HttpDep,
    token: Annotated[str | None, Query(max_length=256)] = None,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
) -> HTMLResponse:
    """Finishes a magic link (`token`) or a Google round trip (`code` + `state`)."""
    if token is not None:
        login_code = await service.complete_email_login(session, redis, settings, token=token)
    elif code is not None and state is not None:
        login_code = await service.complete_google_login(
            session, redis, settings, http, code=code, state=state
        )
    else:
        raise AppError(400, "invalid_link", "This sign-in link is invalid or has expired.")
    return _open_app_page(settings.desktop_deep_link, login_code)


@router.post("/auth/exchange", response_model=TokenResponse)
async def exchange(
    body: ExchangeRequest, session: SessionDep, redis: RedisDep, settings: SettingsDep
) -> TokenResponse:
    issued = await service.exchange_code(
        session,
        redis,
        settings,
        code=body.code,
        code_verifier=body.code_verifier,
        device_id=body.device_id,
        device_name=body.device_name,
    )
    return TokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
        user=UserOut.model_validate(issued.user),
    )


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    issued = await service.refresh_tokens(session, settings, refresh_token=body.refresh_token)
    return TokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
        user=UserOut.model_validate(issued.user),
    )


@router.post("/auth/logout", status_code=204)
async def logout(body: LogoutRequest, session: SessionDep) -> Response:
    await service.logout(session, refresh_token=body.refresh_token)
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> MeResponse:
    today = await usage_today(session, user.id)
    return MeResponse(
        **UserOut.model_validate(user).model_dump(),
        daily_token_budget=user.daily_token_budget,
        input_tokens_today=today.input_tokens,
        output_tokens_today=today.output_tokens,
        min_desktop_version=settings.min_desktop_version,
    )
