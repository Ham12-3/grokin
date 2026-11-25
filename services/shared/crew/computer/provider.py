"""ComputerProvider: one interface for the cloud computer, whoever hosts it.

`docker` runs one container per user on this machine (local dev). `e2b` is the production
provider (not built yet). `local` is a plain folder with no browser or terminal, for tests
and for servers without Docker.

The backend talks to the machine only through its control server (see
`infra/computer/control_server.py`). Chromium's debugging port never leaves the machine,
so browser actions are a provider method rather than a CDP URL.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from crew.config import Settings

DISPLAYS = range(1, 7)
ComputerState = Literal["running", "stopped", "missing"]


class ComputerError(Exception):
    """A failure the user or the model can be told about. The message is safe to show."""


@dataclass(frozen=True)
class ComputerHandle:
    user_id: uuid.UUID
    base_url: str  # the control server, reachable from the backend only
    token: str


@dataclass(frozen=True)
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


@dataclass(frozen=True)
class FileEntry:
    name: str
    is_dir: bool
    size: int


def control_token(settings: Settings, user_id: uuid.UUID) -> str:
    """The machine's own token, derived so it never has to be stored in the clear."""
    secret = settings.computer_token_secret or settings.jwt_secret
    return hmac.new(secret.encode(), f"computer:{user_id}".encode(), hashlib.sha256).hexdigest()


class ComputerProvider(Protocol):
    name: str

    async def ensure(self, user_id: uuid.UUID) -> ComputerHandle:
        """Creates or resumes the user's machine and waits until it answers."""
        ...

    async def stop(self, user_id: uuid.UUID) -> None:
        """Pauses the machine. Files and browser logins are kept."""
        ...

    async def state(self, user_id: uuid.UUID) -> ComputerState: ...

    async def exec(
        self, handle: ComputerHandle, cmd: str, timeout_s: float, display: int | None = None
    ) -> ExecResult: ...

    async def read_file(self, handle: ComputerHandle, path: str) -> bytes: ...

    async def write_file(self, handle: ComputerHandle, path: str, data: bytes) -> None: ...

    async def list_dir(self, handle: ComputerHandle, path: str) -> list[FileEntry]: ...

    async def start_display(self, handle: ComputerHandle, display: int) -> None: ...

    async def browser(
        self, handle: ComputerHandle, display: int, action: str, **args: Any
    ) -> dict[str, Any]: ...

    def vnc_url(self, handle: ComputerHandle, display: int) -> str:
        """A ws:// URL for the display's live screen.

        It carries the token: never give it to a client.
        """
        ...

    async def aclose(self) -> None: ...
