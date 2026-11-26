"""Error reporting (Sentry). Off unless SENTRY_DSN is set.

Reports say where the code failed, never what the user or a Bot said: request bodies,
headers, cookies, query strings, local variables, breadcrumbs and extra data are removed
before anything leaves the server.
"""

from typing import Any

import sentry_sdk

from crew import __version__
from crew.config import Settings

DROP_KEYS = ("extra", "breadcrumbs", "user", "contexts", "modules", "server_name")


def scrub(event: Any, _hint: Any = None) -> Any:
    """`before_send`: keep the error type and stack, drop everything that could hold data."""
    if not isinstance(event, dict):
        return event
    for key in DROP_KEYS:
        event.pop(key, None)
    request = event.get("request")
    if isinstance(request, dict):
        # Method and path say which route failed; ids in paths are not content.
        url = str(request.get("url", "")).split("?")[0]
        event["request"] = {"method": request.get("method"), "url": url}
    for entry in (event.get("exception") or {}).get("values") or []:
        # The message of an error can quote user text (for example a validation error).
        entry["value"] = ""
        for frame in (entry.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
            frame.pop("pre_context", None)
            frame.pop("post_context", None)
    event.pop("message", None)
    event.pop("logentry", None)
    return event


def _no_breadcrumbs(_crumb: Any, _hint: Any = None) -> None:
    return None


def configure(settings: Settings, component: str) -> bool:
    """Starts error reporting for the API or the worker. Returns whether it is on."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        release=f"crew-{component}@{__version__}",
        environment=settings.crew_env,
        max_request_body_size="never",
        before_send=scrub,
        before_breadcrumb=_no_breadcrumbs,
        traces_sample_rate=0.0,
    )
    return True
