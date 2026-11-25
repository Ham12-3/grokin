"""Browser tools: the Bot's own Chromium on its screen of the user's computer.

Pages are read as text plus a numbered list of things that can be clicked or typed into.
Everything a page says is untrusted data. Clicking something whose label looks like
sending, paying, deleting or sharing is risky and needs approval.
"""

import re
from typing import Any
from urllib.parse import urlsplit

from crew.computer.provider import ComputerError
from crew.tools.net import Resolver, check_url, system_resolver
from crew.tools.registry import Args, Preview, Risk, Tool, ToolContext, ToolError, ToolOutput

PAGE_TEXT_CHARS = 8000
RISKY_LABEL = re.compile(
    r"\b(send|post|publish|tweet|reply|submit|pay|buy|purchase|order|checkout|subscribe|"
    r"donate|transfer|delete|remove|share|invite|confirm|unsubscribe|deactivate|cancel plan)\b",
    re.IGNORECASE,
)
PURCHASE_LABEL = re.compile(
    r"\b(pay|buy|purchase|order|checkout|subscribe|donate|transfer)\b", re.IGNORECASE
)
# Words that mark a page where submitting a form spends money.
PAYMENT_PAGE = re.compile(
    r"\b(checkout|payment|billing|card number|credit card|debit card|place (your )?order|"
    r"pay now|order total|cvv|cvc)\b",
    re.IGNORECASE,
)
ELEMENT = {"type": "integer", "minimum": 1, "description": "The number of the element"}


def _host(url: str) -> str:
    return urlsplit(url).hostname or "page"


def _format(snapshot: dict[str, Any], ctx: ToolContext) -> tuple[str, str]:
    """Turns a page snapshot into text for the model, and remembers the element labels."""
    elements = [item for item in snapshot.get("elements", []) if isinstance(item, dict)]
    ctx.computer.element_labels.clear()
    lines = []
    for item in elements:
        label = str(item.get("label", ""))
        ctx.computer.element_labels[int(item["id"])] = label
        kind = str(item.get("tag", ""))
        if item.get("type"):
            kind += f" {item['type']}"
        lines.append(f"[{item['id']}] {kind}: {label}")
    url = str(snapshot.get("url", ""))
    title = str(snapshot.get("title", ""))
    text = str(snapshot.get("text", ""))
    ctx.computer.page_url = url
    ctx.computer.page_text = f"{title}\n{text[:PAGE_TEXT_CHARS]}"
    body = text[:PAGE_TEXT_CHARS] + ("\n[page text cut]" if len(text) > PAGE_TEXT_CHARS else "")
    listing = "\n".join(lines) if lines else "(nothing to click or type into)"
    return f"URL: {url}\nTitle: {title}\n\n{body}\n\nElements:\n{listing}", url


async def _act(ctx: ToolContext, action: str, **args: Any) -> dict[str, Any]:
    try:
        handle = await ctx.computer.handle()
        display = await ctx.computer.display()
        return await ctx.computer.provider.browser(handle, display, action, **args)
    except ComputerError as error:
        raise ToolError(str(error)) from error


def _label(args: Args, ctx: ToolContext) -> str:
    try:
        return ctx.computer.element_labels.get(int(args.get("element", 0)), "")
    except (TypeError, ValueError):
        return ""


def click_risk(args: Args, ctx: ToolContext) -> Risk:
    return "risky" if RISKY_LABEL.search(_label(args, ctx)) else "safe"


def type_risk(args: Args, ctx: ToolContext) -> Risk:
    # Pressing Enter submits the form the field is in, whatever its button is called.
    return "risky" if args.get("press_enter") and RISKY_LABEL.search(_label(args, ctx)) else "safe"


def submit_risk(args: Args, ctx: ToolContext) -> Risk:
    """Submitting a form is risky on a page that pays, checks out, sends or deletes."""
    page = f"{ctx.computer.page_url}\n{ctx.computer.page_text}"
    if PAYMENT_PAGE.search(page):
        return "risky"
    # Any send / delete / pay style control on the page: the form may be that one.
    labels = [_label(args, ctx), *ctx.computer.element_labels.values()]
    return "risky" if any(RISKY_LABEL.search(label) for label in labels) else "safe"


def _action_preview(verb: str) -> Any:
    def preview(args: Args, ctx: ToolContext) -> Preview:
        label = _label(args, ctx)[:80]
        host = _host(ctx.computer.page_url) if ctx.computer.page_url else "the page"
        page = f"{ctx.computer.page_url}\n{ctx.computer.page_text}"
        buying = bool(PURCHASE_LABEL.search(label)) or (
            verb == "Submit the form" and bool(PAYMENT_PAGE.search(page))
        )
        what = f"{verb} “{label}”" if label else verb
        context = {"page": ctx.computer.page_url[:300]}
        if label:
            context["item"] = label
        return Preview(
            "purchase" if buying else "generic", f"{what} on {host}", dict(args), context
        )

    return preview


def make_browser_tools(resolver: Resolver = system_resolver) -> list[Tool]:
    async def browser_open(args: Args, ctx: ToolContext) -> ToolOutput:
        # Same guard as web_fetch; the computer's own network rules are the second line.
        await check_url(args["url"], resolver)
        text, url = _format(await _act(ctx, "open", url=args["url"]), ctx)
        return ToolOutput(text, f"Opened {_host(url)}", source=f"web:{_host(url)}")

    async def browser_read(args: Args, ctx: ToolContext) -> ToolOutput:
        text, url = _format(await _act(ctx, "read"), ctx)
        return ToolOutput(text, f"Read {_host(url)}", source=f"web:{_host(url)}")

    async def browser_click(args: Args, ctx: ToolContext) -> ToolOutput:
        label = _label(args, ctx)
        text, url = _format(await _act(ctx, "click", element=args["element"]), ctx)
        return ToolOutput(text, f"Clicked {label[:60]!r}", source=f"web:{_host(url)}")

    async def browser_type(args: Args, ctx: ToolContext) -> ToolOutput:
        label = _label(args, ctx)
        snapshot = await _act(
            ctx,
            "type",
            element=args["element"],
            text=args["text"],
            press_enter=bool(args.get("press_enter", False)),
        )
        text, url = _format(snapshot, ctx)
        return ToolOutput(text, f"Typed into {label[:60]!r}", source=f"web:{_host(url)}")

    async def browser_submit(args: Args, ctx: ToolContext) -> ToolOutput:
        label = _label(args, ctx)
        text, url = _format(await _act(ctx, "submit", element=args["element"]), ctx)
        return ToolOutput(text, f"Submitted the form at {label[:60]!r}", source=f"web:{_host(url)}")

    async def browser_screenshot(args: Args, ctx: ToolContext) -> ToolOutput:
        result = await _act(ctx, "screenshot")
        path = str(result.get("path", ""))
        return ToolOutput(f"Saved a screenshot to {path}", f"Saved a screenshot to {path}")

    no_args = {"type": "object", "properties": {}, "additionalProperties": False}
    return [
        Tool(
            name="browser_open",
            description=(
                "Open a web page in your browser. Returns the page text and a numbered list "
                "of elements you can click or type into. Use it for sites that need a login "
                "or JavaScript; for plain reading, web_fetch is faster."
            ),
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string", "maxLength": 2000}},
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=browser_open,
            summary=lambda args: f"Opened {_host(str(args.get('url', '')))}",
            read_only=True,
            timeout_seconds=200.0,
        ),
        Tool(
            name="browser_read",
            description="Read the page that is open in your browser now.",
            input_schema=no_args,
            handler=browser_read,
            summary=lambda args: "Read the page",
            read_only=True,
            timeout_seconds=200.0,
        ),
        Tool(
            name="browser_click",
            description="Click an element by its number from the latest page reading.",
            input_schema={
                "type": "object",
                "properties": {"element": ELEMENT},
                "required": ["element"],
                "additionalProperties": False,
            },
            handler=browser_click,
            summary=lambda args: f"Clicked element {args.get('element', '?')}",
            read_only=False,
            risk=click_risk,
            preview=_action_preview("Click"),
            timeout_seconds=200.0,
        ),
        Tool(
            name="browser_type",
            description=(
                "Type text into a field by its number. Never type passwords or codes: "
                "call request_takeover so the user can do it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "element": ELEMENT,
                    "text": {"type": "string", "maxLength": 10_000},
                    "press_enter": {"type": "boolean"},
                },
                "required": ["element", "text"],
                "additionalProperties": False,
            },
            handler=browser_type,
            summary=lambda args: f"Typed into element {args.get('element', '?')}",
            read_only=False,
            risk=type_risk,
            preview=_action_preview("Type and press Enter in"),
            timeout_seconds=200.0,
        ),
        Tool(
            name="browser_submit",
            description=(
                "Submit the form that a field belongs to (like pressing Enter in it). Give "
                "the number of a field in that form."
            ),
            input_schema={
                "type": "object",
                "properties": {"element": ELEMENT},
                "required": ["element"],
                "additionalProperties": False,
            },
            handler=browser_submit,
            summary=lambda args: f"Submitted the form at element {args.get('element', '?')}",
            read_only=False,
            risk=submit_risk,
            preview=_action_preview("Submit the form"),
            timeout_seconds=200.0,
        ),
        Tool(
            name="browser_screenshot",
            description="Save a picture of the page to /workspace/outputs/screenshots.",
            input_schema=no_args,
            handler=browser_screenshot,
            summary=lambda args: "Took a screenshot",
            read_only=True,
            timeout_seconds=200.0,
        ),
    ]


def make_takeover_tool() -> Tool:
    async def request_takeover(args: Args, ctx: ToolContext) -> ToolOutput:
        await ctx.computer.display()  # the user needs a screen to take over
        await ctx.takeover(args["reason"])
        return ToolOutput(
            "The user has given control back. Read the page again before you continue.",
            "You gave control back",
        )

    return Tool(
        name="request_takeover",
        description=(
            "Ask the user to take over your screen for something only they can do: signing "
            "in, a CAPTCHA, a passkey or a two-step code. The run waits until they give "
            "control back. Say exactly what you need."
        ),
        input_schema={
            "type": "object",
            "properties": {"reason": {"type": "string", "minLength": 3, "maxLength": 300}},
            "required": ["reason"],
            "additionalProperties": False,
        },
        handler=request_takeover,
        summary=lambda args: f"Needs you: {str(args.get('reason', ''))[:200]}",
        read_only=True,
        timeout_seconds=3600.0,  # the wait is bounded by TAKEOVER_TIMEOUT_SECONDS
    )
