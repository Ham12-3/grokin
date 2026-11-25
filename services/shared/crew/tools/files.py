"""files_read, files_write and files_list, on the user's computer (`/workspace`)."""

from crew.computer.provider import ComputerError
from crew.tools.registry import Args, Tool, ToolContext, ToolError, ToolOutput

PATH_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 300,
    "description": "A path inside your workspace, for example notes.md or reports/q3.md",
}


def _size(count: int) -> str:
    return f"{count} bytes" if count < 1024 else f"{count / 1024:.1f} kB"


async def _files_write(args: Args, ctx: ToolContext) -> ToolOutput:
    data = args["content"].encode("utf-8")
    if len(data) > ctx.settings.file_max_bytes:
        raise ToolError(f"That file is too large (limit {_size(ctx.settings.file_max_bytes)}).")
    try:
        handle = await ctx.computer.handle()
        await ctx.computer.provider.write_file(handle, args["path"], data)
    except ComputerError as error:
        raise ToolError(str(error)) from error
    summary = f"Wrote {args['path']} ({_size(len(data))})"
    return ToolOutput(summary, summary)


async def _files_read(args: Args, ctx: ToolContext) -> ToolOutput:
    try:
        handle = await ctx.computer.handle()
        data = await ctx.computer.provider.read_file(handle, args["path"])
    except ComputerError as error:
        raise ToolError(str(error)) from error
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ToolError(f"{args['path']} is not a text file.") from error
    # File contents may have come from the web, so they are data, not instructions.
    return ToolOutput(text, f"Read {args['path']} ({_size(len(data))})", source="file")


async def _files_list(args: Args, ctx: ToolContext) -> ToolOutput:
    path = args.get("dir", ".")
    try:
        handle = await ctx.computer.handle()
        entries = await ctx.computer.provider.list_dir(handle, path)
    except ComputerError as error:
        raise ToolError(str(error)) from error
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
            timeout_seconds=150.0,  # the first use may have to start the computer
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
            timeout_seconds=150.0,
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
            timeout_seconds=150.0,
        ),
    ]
