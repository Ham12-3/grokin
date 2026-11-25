"""files_read, files_write and files_list.

For now files live in a local folder per user (`data/workspaces/{user_id}`). Phase 4 swaps
`LocalWorkspace` for the cloud computer behind the same `Workspace` interface.
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from crew.config import Settings
from crew.tools.registry import Args, Tool, ToolContext, ToolError, ToolOutput

PATH_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 300,
    "description": "A path inside your workspace, for example notes.md or reports/q3.md",
}


@dataclass(frozen=True)
class FileEntry:
    name: str
    is_dir: bool
    size: int


class Workspace(Protocol):
    async def read(self, path: str) -> bytes: ...
    async def write(self, path: str, data: bytes) -> None: ...
    async def list(self, path: str) -> list[FileEntry]: ...


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
            raise ToolError("That path is outside your workspace.")
        target = (self._root / relative).resolve()
        # resolve() follows symlinks, so a link pointing outside is caught here too.
        if target != self._root and self._root not in target.parents:
            raise ToolError("That path is outside your workspace.")
        return target

    async def read(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"There is no file at {path}.")
        return await asyncio.to_thread(target.read_bytes)

    async def write(self, path: str, data: bytes) -> None:
        target = self._resolve(path)
        if target == self._root or target.is_dir():
            raise ToolError("That path is a folder, not a file.")

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        await asyncio.to_thread(_write)

    async def list(self, path: str) -> list[FileEntry]:
        target = self._resolve(path)
        if not target.exists():
            if target == self._root:
                return []
            raise ToolError(f"There is no folder at {path}.")
        if not target.is_dir():
            raise ToolError(f"{path} is a file, not a folder.")

        def _list() -> list[FileEntry]:
            return [
                FileEntry(
                    child.name, child.is_dir(), child.stat().st_size if child.is_file() else 0
                )
                for child in sorted(target.iterdir(), key=lambda item: item.name.lower())
            ]

        return await asyncio.to_thread(_list)


def workspace_for(settings: Settings, user_id: uuid.UUID) -> Workspace:
    return LocalWorkspace(Path(settings.workspaces_dir) / str(user_id))


def _size(count: int) -> str:
    return f"{count} bytes" if count < 1024 else f"{count / 1024:.1f} kB"


async def _files_write(args: Args, ctx: ToolContext) -> ToolOutput:
    data = args["content"].encode("utf-8")
    if len(data) > ctx.settings.file_max_bytes:
        raise ToolError(f"That file is too large (limit {_size(ctx.settings.file_max_bytes)}).")
    await workspace_for(ctx.settings, ctx.user_id).write(args["path"], data)
    summary = f"Wrote {args['path']} ({_size(len(data))})"
    return ToolOutput(summary, summary)


async def _files_read(args: Args, ctx: ToolContext) -> ToolOutput:
    data = await workspace_for(ctx.settings, ctx.user_id).read(args["path"])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ToolError(f"{args['path']} is not a text file.") from error
    # File contents may have come from the web, so they are data, not instructions.
    return ToolOutput(text, f"Read {args['path']} ({_size(len(data))})", source="file")


async def _files_list(args: Args, ctx: ToolContext) -> ToolOutput:
    path = args.get("dir", ".")
    entries = await workspace_for(ctx.settings, ctx.user_id).list(path)
    if not entries:
        return ToolOutput("The folder is empty.", f"Listed {path} (empty)")
    lines = [
        f"{entry.name}/" if entry.is_dir else f"{entry.name} ({_size(entry.size)})"
        for entry in entries
    ]
    return ToolOutput("\n".join(lines), f"Listed {path} ({len(entries)} items)", source="file")


def make_file_tools() -> list[Tool]:
    return [
        Tool(
            name="files_write",
            description="Create or replace a text file in your workspace.",
            input_schema={
                "type": "object",
                "properties": {"path": PATH_SCHEMA, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            handler=_files_write,
            summary=lambda args: f"Wrote {str(args.get('path', ''))[:120]}",
            read_only=False,
        ),
        Tool(
            name="files_read",
            description="Read a text file from your workspace.",
            input_schema={
                "type": "object",
                "properties": {"path": PATH_SCHEMA},
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=_files_read,
            summary=lambda args: f"Read {str(args.get('path', ''))[:120]}",
            read_only=True,
        ),
        Tool(
            name="files_list",
            description="List the files in a folder of your workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "dir": {**PATH_SCHEMA, "description": "Folder path; omit for the top"}
                },
                "additionalProperties": False,
            },
            handler=_files_list,
            summary=lambda args: f"Listed {str(args.get('dir', 'your files'))[:120]}",
            read_only=True,
        ),
    ]
