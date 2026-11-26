"""library_add: put a file the Bot made into the user's Library.

Files saved under /workspace/outputs are also picked up when a run ends
(`collect_outputs`), so a Bot that forgets to call the tool still delivers its work.
"""

import uuid
from typing import Any

import structlog

from crew.computer.provider import ComputerError
from crew.errors import AppError
from crew.library import service
from crew.models import LibraryItem
from crew.tools.registry import Args, Tool, ToolContext, ToolError, ToolOutput

log = structlog.get_logger(__name__)

OUTPUTS = "outputs"
MAX_AUTO_FILES = 20
# The Bot's own screenshots land here; they are working material, not deliverables.
SKIP_FOLDERS = ("screenshots",)


async def _add(ctx: ToolContext, path: str, title: str) -> LibraryItem:
    if ctx.session_factory is None or ctx.storage is None or ctx.redis is None:
        raise ToolError("The Library is not available here.")
    relative = path.strip().removeprefix("/workspace/").lstrip("/")
    try:
        handle = await ctx.computer.handle()
        data = await ctx.computer.provider.read_file(handle, relative)
    except ComputerError as error:
        raise ToolError(str(error)) from error
    async with ctx.session_factory() as session:
        try:
            item = await service.add_file(
                session,
                ctx.storage,
                user_id=ctx.user_id,
                bot_id=ctx.bot_id,
                run_id=ctx.run_id,
                path=f"/workspace/{relative}",
                title=title,
                data=data,
            )
        except AppError as error:
            raise ToolError(error.message) from error
        if ctx.chat_id is not None and ctx.bot_id is not None:
            await service.post_file_card(session, ctx.redis, ctx.chat_id, ctx.bot_id, item)
    return item


async def _library_add(args: Args, ctx: ToolContext) -> ToolOutput:
    item = await _add(ctx, args["path"], str(args.get("title", "")))
    return ToolOutput(
        f"Added to the user's Library as “{item.title}”.", f"Added {item.title} to the Library"
    )


def make_library_tool() -> Tool:
    return Tool(
        name="library_add",
        description=(
            "Put a file you made into the user's Library so they can open and download it. "
            "Use it for the finished result of a task (a report, a spreadsheet, an image). "
            "Save the file under outputs/ first."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 500},
                "title": {"type": "string", "maxLength": 200},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=_library_add,
        summary=lambda args: f"Added {str(args.get('path', ''))[:80]} to the Library",
        # It only copies the user's own file to the user's own Library.
        read_only=True,
        timeout_seconds=120.0,
    )


async def collect_outputs(ctx: ToolContext, known: set[str]) -> list[str]:
    """After a run: adds files in /workspace/outputs that are not in the Library yet.

    `known` holds the paths this run already added. Returns the new titles.
    """
    if ctx.session_factory is None or ctx.storage is None or not ctx.computer.started:
        return []
    added: list[str] = []
    try:
        handle = await ctx.computer.handle()
        folders = [OUTPUTS]
        files: list[str] = []
        while folders and len(files) < MAX_AUTO_FILES * 3:
            folder = folders.pop(0)
            for entry in await ctx.computer.provider.list_dir(handle, folder):
                path = f"{folder}/{entry.name}"
                if entry.is_dir:
                    if entry.name not in SKIP_FOLDERS and path.count("/") < 3:
                        folders.append(path)
                elif 0 < entry.size <= service.MAX_FILE_BYTES:
                    files.append(path)
        async with ctx.session_factory() as session:
            existing: dict[str, Any] = {
                str(item.path): item.size_bytes
                for item in await service.list_items(session, ctx.user_id)
            }
        for path in files:
            full = f"/workspace/{path}"
            if full in known or len(added) >= MAX_AUTO_FILES:
                continue
            data = await ctx.computer.provider.read_file(handle, path)
            if existing.get(full) == len(data):
                continue  # already there and unchanged
            item = await _add(ctx, path, "")
            added.append(item.title)
    except (ComputerError, ToolError) as error:
        log.info("library.collect_failed", run_id=str(ctx.run_id), reason=str(error))
    return added


def run_paths(calls: list[tuple[str, dict[str, Any]]]) -> set[str]:
    """Paths this run already added with `library_add` (so they are not added twice)."""
    paths = set()
    for tool, args in calls:
        if tool == "library_add":
            relative = str(args.get("path", "")).strip().removeprefix("/workspace/").lstrip("/")
            paths.add(f"/workspace/{relative}")
    return paths


__all__ = ["collect_outputs", "make_library_tool", "run_paths", "uuid"]
