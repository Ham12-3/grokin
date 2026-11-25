"""A plain folder per user: files only, no browser, terminal or screen.

Used by tests and by servers without Docker (`COMPUTER_PROVIDER=local`).
"""

import asyncio
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from crew.computer.provider import (
    ComputerError,
    ComputerHandle,
    ComputerState,
    ExecResult,
    FileEntry,
)
from crew.config import Settings

NEEDS_COMPUTER = "This needs the cloud computer, which is not turned on for this server."
OUTSIDE = "That path is outside your workspace."


class LocalWorkspace:
    """A folder on the backend machine. Every path is confined to it."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _resolve(self, path: str) -> Path:
        cleaned = path.replace("\\", "/").strip()
        if cleaned.startswith("/workspace"):
            cleaned = cleaned[len("/workspace") :]
        relative = PurePosixPath(cleaned.lstrip("/") or ".")
        if relative.is_absolute() or ".." in relative.parts or ":" in cleaned:
            raise ComputerError(OUTSIDE)
        target = (self._root / relative).resolve()
        # resolve() follows symlinks, so a link pointing outside is caught here too.
        if target != self._root and self._root not in target.parents:
            raise ComputerError(OUTSIDE)
        return target

    async def read(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.is_file():
            raise ComputerError(f"There is no file at {path}.")
        return await asyncio.to_thread(target.read_bytes)

    async def write(self, path: str, data: bytes) -> None:
        target = self._resolve(path)
        if target == self._root or target.is_dir():
            raise ComputerError("That path is a folder, not a file.")

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        await asyncio.to_thread(_write)

    async def list(self, path: str) -> list[FileEntry]:
        target = self._resolve(path)
        if not target.exists():
            if target == self._root:
                return []
            raise ComputerError(f"There is no folder at {path}.")
        if not target.is_dir():
            raise ComputerError(f"{path} is a file, not a folder.")

        def _list() -> list[FileEntry]:
            children = sorted(target.iterdir(), key=lambda item: item.name.lower())
            return [
                FileEntry(
                    child.name, child.is_dir(), child.stat().st_size if child.is_file() else 0
                )
                for child in children
            ]

        return await asyncio.to_thread(_list)


class LocalProvider:
    name = "local"

    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.workspaces_dir)

    def _workspace(self, handle: ComputerHandle) -> LocalWorkspace:
        return LocalWorkspace(self._root / str(handle.user_id))

    async def ensure(self, user_id: uuid.UUID) -> ComputerHandle:
        return ComputerHandle(user_id, "local://", "")

    async def stop(self, user_id: uuid.UUID) -> None:
        return None

    async def state(self, user_id: uuid.UUID) -> ComputerState:
        return "running"

    async def exec(
        self, handle: ComputerHandle, cmd: str, timeout_s: float, display: int | None = None
    ) -> ExecResult:
        raise ComputerError(NEEDS_COMPUTER)

    async def read_file(self, handle: ComputerHandle, path: str) -> bytes:
        return await self._workspace(handle).read(path)

    async def write_file(self, handle: ComputerHandle, path: str, data: bytes) -> None:
        await self._workspace(handle).write(path, data)

    async def list_dir(self, handle: ComputerHandle, path: str) -> list[FileEntry]:
        return await self._workspace(handle).list(path)

    async def start_display(self, handle: ComputerHandle, display: int) -> None:
        raise ComputerError(NEEDS_COMPUTER)

    async def browser(
        self, handle: ComputerHandle, display: int, action: str, **args: Any
    ) -> dict[str, Any]:
        raise ComputerError(NEEDS_COMPUTER)

    def vnc_url(self, handle: ComputerHandle, display: int) -> str:
        raise ComputerError(NEEDS_COMPUTER)

    async def aclose(self) -> None:
        return None
