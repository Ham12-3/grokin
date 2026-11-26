"""Composio: holds the OAuth tokens for Gmail, Google Calendar, Slack and Notion and runs
their actions (REST v3.1, https://docs.composio.dev).

Written from Composio's published API on 2026-11-26. The request shapes are covered by
tests against a stub; they have NOT been run against a real Composio account yet.
"""

import uuid
from typing import Any

import httpx

from crew.connectors.backend import ConnectorError

BASE_URL = "https://backend.composio.dev/api/v3.1"
TOOLKITS = {"gmail": "gmail", "gcal": "googlecalendar", "slack": "slack", "notion": "notion"}
STATUS = {"ACTIVE": "connected", "INITIALIZING": "pending", "INITIATED": "pending"}


def _request(action: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Maps one of our app actions to a Composio tool and its argument names."""

    def only(values: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in values.items() if value not in (None, "")}

    if action == "email_search":
        return "GMAIL_FETCH_EMAILS", only(
            {"query": args.get("query"), "max_results": int(args.get("limit", 5))}
        )
    if action == "email_read":
        return "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", {"message_id": args["id"]}
    if action == "email_send":
        if args.get("reply_to_id"):
            return "GMAIL_REPLY_TO_THREAD", {
                "thread_id": args["reply_to_id"],
                "message_body": args["body"],
                "recipient_email": args["to"],
            }
        return "GMAIL_SEND_EMAIL", {
            "recipient_email": args["to"],
            "subject": args["subject"],
            "body": args["body"],
        }
    if action == "calendar_list":
        return "GOOGLECALENDAR_EVENTS_LIST", only(
            {
                "calendarId": "primary",
                "timeMin": args.get("start"),
                "timeMax": args.get("end"),
                "singleEvents": True,
            }
        )
    if action == "calendar_create":
        return "GOOGLECALENDAR_CREATE_EVENT", only(
            {
                "summary": args["title"],
                "start_datetime": args["start"],
                "end_datetime": args["end"],
                "attendees": args.get("attendees"),
                "description": args.get("description"),
                "create_meeting_room": False,
            }
        )
    if action == "slack_read":
        return "SLACK_FETCH_CONVERSATION_HISTORY", {
            "channel": args["channel"],
            "limit": int(args.get("limit", 20)),
        }
    if action == "slack_post":
        return "SLACK_SEND_MESSAGE", {"channel": args["channel"], "markdown_text": args["text"]}
    if action == "notion_search":
        return "NOTION_SEARCH_NOTION_PAGE", {"query": args["query"]}
    if action == "notion_update":
        return "NOTION_UPDATE_PAGE_MARKDOWN", {
            "page_id": args["page_id"],
            "type": "update_content",
            "update_content": args["content"],
        }
    raise ConnectorError("That action is not available.")


class ComposioBackend:
    name = "composio"

    def __init__(
        self, api_key: str, http: httpx.AsyncClient, callback_url: str | None = None
    ) -> None:
        self._headers = {"x-api-key": api_key}
        self._http = http
        self._callback_url = callback_url

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._http.request(
                method, f"{BASE_URL}{path}", headers=self._headers, timeout=60.0, **kwargs
            )
        except httpx.HTTPError as error:
            raise ConnectorError("The app service could not be reached. Try again.") from error
        if response.status_code >= 400:
            # Their error text can hold ids; say only what happened.
            raise ConnectorError(f"The app service refused the request ({response.status_code}).")
        return response.json()

    async def _auth_config(self, toolkit: str) -> str:
        found = await self._call(
            "GET",
            "/auth_configs",
            params={"toolkit_slug": toolkit, "is_composio_managed": "true", "limit": 10},
        )
        for item in found.get("items", []):
            if item.get("status", "ENABLED") == "ENABLED":
                return str(item["id"])
        created = await self._call(
            "POST",
            "/auth_configs",
            json={
                "toolkit": {"slug": toolkit},
                "auth_config": {"type": "use_composio_managed_auth"},
            },
        )
        return str(created["auth_config"]["id"])

    async def connect(self, user_id: uuid.UUID, kind: str) -> tuple[str, str | None]:
        toolkit = TOOLKITS[kind]
        body: dict[str, Any] = {
            "auth_config_id": await self._auth_config(toolkit),
            "user_id": str(user_id),
        }
        if self._callback_url:
            body["callback_url"] = self._callback_url
        link = await self._call("POST", "/connected_accounts/link", json=body)
        return str(link["connected_account_id"]), str(link["redirect_url"])

    async def status(self, connection_id: str) -> str:
        account = await self._call("GET", f"/connected_accounts/{connection_id}")
        return STATUS.get(str(account.get("status")), "error")

    async def disconnect(self, connection_id: str) -> None:
        await self._call(
            "DELETE", f"/connected_accounts/{connection_id}", params={"revoke_on_delete": "true"}
        )

    async def execute(
        self, user_id: uuid.UUID, connection_id: str, action: str, args: dict[str, Any]
    ) -> Any:
        slug, arguments = _request(action, args)
        result = await self._call(
            "POST",
            f"/tools/execute/{slug}",
            json={
                "user_id": str(user_id),
                "connected_account_id": connection_id,
                "arguments": arguments,
            },
        )
        if not result.get("successful"):
            raise ConnectorError(f"The app reported an error: {str(result.get('error'))[:300]}")
        return result.get("data")

    async def recent_ids(self, user_id: uuid.UUID, connection_id: str, event: str) -> list[str]:
        """Polled once a minute for routines triggered by new email."""
        if event != "new_email":
            return []  # Slack needs a channel and its own app setup: not supported yet
        data = await self.execute(
            user_id, connection_id, "email_search", {"query": "in:inbox newer_than:1d", "limit": 10}
        )
        messages = data.get("messages", []) if isinstance(data, dict) else []
        ids = [
            str(item.get("messageId") or item.get("message_id") or item.get("id") or "")
            for item in messages
            if isinstance(item, dict)
        ]
        return [item for item in ids if item]
