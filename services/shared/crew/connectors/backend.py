"""Where connected apps live: the service that holds OAuth tokens and runs app actions.

Crew never stores app tokens itself. `ComposioBackend` (in `composio.py`) is the real one;
`FakeBackend` stands in for it in development and tests: "connecting" works at once, reads
return sample data and sends are written to `connector_log` instead of going anywhere.
"""

import uuid
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew.models import ConnectorLog

KINDS: dict[str, str] = {
    "gmail": "Gmail",
    "gcal": "Google Calendar",
    "slack": "Slack",
    "notion": "Notion",
}


class ConnectorError(Exception):
    """An app could not be reached or refused. The message is safe to show."""


class ConnectorBackend(Protocol):
    name: str

    async def connect(self, user_id: uuid.UUID, kind: str) -> tuple[str, str | None]:
        """Starts connecting an app. Returns (connection id, URL to open or None)."""
        ...

    async def status(self, connection_id: str) -> str:
        """connected | pending | error"""
        ...

    async def disconnect(self, connection_id: str) -> None: ...

    async def execute(
        self, user_id: uuid.UUID, connection_id: str, action: str, args: dict[str, Any]
    ) -> Any:
        """Runs one app action (see `crew.tools.connectors.ACTIONS`). Returns its data."""
        ...

    async def recent_ids(self, user_id: uuid.UUID, connection_id: str, event: str) -> list[str]:
        """Ids of the newest items for an event (new_email, new_message), newest first."""
        ...


SAMPLE_EMAILS = [
    {
        "id": f"msg-{number}",
        "from": sender,
        "subject": subject,
        "snippet": snippet,
        "unread": True,
    }
    for number, (sender, subject, snippet) in enumerate(
        [
            ("sam@example.com", "Q3 report draft", "Can you look at section 2 before Friday?"),
            ("billing@example.com", "Your invoice is ready", "Invoice 1042 for November."),
            ("pat@example.com", "Lunch on Thursday?", "The new place on Main Street at 12:30."),
            ("news@example.com", "This week in Tauri", "Tauri 2.9 is out with window fixes."),
            ("hr@example.com", "Holiday schedule", "The office is closed from the 24th."),
        ],
        start=1,
    )
]


class FakeBackend:
    """Development and tests only. Nothing leaves this server."""

    name = "fake"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        # Tests (and nothing else) put ids here to simulate new mail or messages.
        self.events: dict[tuple[str, str], list[str]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def connect(self, user_id: uuid.UUID, kind: str) -> tuple[str, str | None]:
        return f"fake-{kind}-{user_id}", None  # connected at once: no page to open

    async def status(self, connection_id: str) -> str:
        return "connected"

    async def disconnect(self, connection_id: str) -> None:
        return None

    async def _log(self, user_id: uuid.UUID, action: str, payload: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            session.add(ConnectorLog(user_id=user_id, tool=action, payload=payload))
            await session.commit()

    async def execute(
        self, user_id: uuid.UUID, connection_id: str, action: str, args: dict[str, Any]
    ) -> Any:
        self.calls.append((action, args))
        if action == "email_search":
            return {"emails": SAMPLE_EMAILS[: int(args.get("limit", 5))]}
        if action == "email_read":
            found = next((mail for mail in SAMPLE_EMAILS if mail["id"] == args.get("id")), None)
            if found is None:
                raise ConnectorError("There is no email with that id.")
            return {**found, "body": f"{found['snippet']}\n\nThanks,\n{found['from']}"}
        if action == "calendar_list":
            return {"events": [{"id": "evt-1", "title": "Team sync", "start": "09:30"}]}
        if action == "slack_read":
            return {"messages": [{"user": "sam", "text": "Is the report ready?"}]}
        if action == "notion_search":
            return {"pages": [{"id": "page-1", "title": "Project plan"}]}
        if action in ("email_send", "calendar_create", "slack_post", "notion_update"):
            await self._log(user_id, action, args)
            return {"ok": True}
        raise ConnectorError("That action is not available.")

    async def recent_ids(self, user_id: uuid.UUID, connection_id: str, event: str) -> list[str]:
        return list(self.events.get((connection_id, event), []))


def create_backend(
    settings: Any, session_factory: async_sessionmaker[AsyncSession], http: Any
) -> ConnectorBackend | None:
    """Composio when a key is set; the stand-in in development; nothing in production."""
    from crew.connectors.composio import ComposioBackend

    if settings.composio_api_key:
        return ComposioBackend(settings.composio_api_key, http)
    if settings.crew_env in ("dev", "test"):
        return FakeBackend(session_factory)
    return None
