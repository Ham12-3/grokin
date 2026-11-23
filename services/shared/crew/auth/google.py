"""Google OAuth (authorization code flow). Only the verified email and profile are used."""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import structlog

from crew.config import Settings
from crew.errors import AppError

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GoogleProfile:
    email: str
    name: str | None
    avatar_url: str | None


def require_google(settings: Settings) -> None:
    if not (settings.google_client_id and settings.google_client_secret):
        raise AppError(503, "google_not_configured", "Google sign-in is not set up on this server.")


def callback_url(settings: Settings) -> str:
    return f"{settings.api_base_url}{settings.api_prefix}/auth/callback"


def authorize_url(settings: Settings, state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": callback_url(settings),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{settings.google_auth_url}?{query}"


async def fetch_profile(http: httpx.AsyncClient, settings: Settings, code: str) -> GoogleProfile:
    """Swaps Google's code for an access token, then reads the user's profile."""
    failed = AppError(502, "google_failed", "Google sign-in failed. Try again.")
    try:
        token_resp = await http.post(
            settings.google_token_url,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": callback_url(settings),
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        google_token = token_resp.json()["access_token"]
        info_resp = await http.get(
            settings.google_userinfo_url, headers={"Authorization": f"Bearer {google_token}"}
        )
        info_resp.raise_for_status()
        info = info_resp.json()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("auth.google_failed", error=type(exc).__name__)
        raise failed from exc

    email = info.get("email")
    if not isinstance(email, str) or not email:
        raise failed
    if info.get("email_verified") is not True:
        raise AppError(403, "email_not_verified", "Your Google email address is not verified.")
    return GoogleProfile(email=email, name=info.get("name"), avatar_url=info.get("picture"))
