"""Sends magic links. In dev (no SMTP_URL) the link is printed to the API log instead."""

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import unquote, urlsplit

import structlog

from crew.config import Settings

log = structlog.get_logger(__name__)


class Mailer(Protocol):
    async def send_magic_link(self, email: str, link: str) -> None: ...


class DevLogMailer:
    """Dev only: prints the link so you can click it. Never used in prod."""

    async def send_magic_link(self, email: str, link: str) -> None:
        log.info("auth.magic_link", email=email, link=link)


class SmtpMailer:
    """Plain SMTP. URL form: smtp://user:pass@host:587 or smtps://user:pass@host:465."""

    def __init__(self, smtp_url: str, email_from: str) -> None:
        self._url = urlsplit(smtp_url)
        self._from = email_from

    def _send(self, message: EmailMessage) -> None:
        host = self._url.hostname or "localhost"
        use_ssl = self._url.scheme == "smtps"
        port = self._url.port or (465 if use_ssl else 587)
        smtp: smtplib.SMTP = (
            smtplib.SMTP_SSL(host, port, timeout=10)
            if use_ssl
            else smtplib.SMTP(host, port, timeout=10)
        )
        with smtp:
            if not use_ssl:
                smtp.starttls()
            if self._url.username:
                smtp.login(unquote(self._url.username), unquote(self._url.password or ""))
            smtp.send_message(message)

    async def send_magic_link(self, email: str, link: str) -> None:
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = email
        message["Subject"] = "Your Crew sign-in link"
        message.set_content(
            f"Click to sign in to Crew:\n\n{link}\n\n"
            "This link works once and expires soon. If you did not ask for it, ignore this email."
        )
        await asyncio.to_thread(self._send, message)


def create_mailer(settings: Settings) -> Mailer:
    if settings.smtp_url:
        return SmtpMailer(settings.smtp_url, settings.email_from)
    if settings.crew_env == "prod":
        raise RuntimeError("SMTP_URL must be set in prod: magic links are never logged there.")
    return DevLogMailer()
