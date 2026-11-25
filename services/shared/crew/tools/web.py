"""web_search and web_fetch. Both run on the backend; results are untrusted data."""

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import httpx

from crew.tools.net import Resolver, safe_get, system_resolver
from crew.tools.registry import Args, Tool, ToolContext, ToolError, ToolOutput

SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "head"}
BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre", "table",
}  # fmt: skip
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml")
USER_AGENT = "CrewBot/0.1 (+web_fetch)"


class _TextExtractor(HTMLParser):
    """Readable text from HTML: drops scripts and styles, keeps the title and line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._skip_depth == 0:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Returns (title, readable text)."""
    extractor = _TextExtractor()
    extractor.feed(html)
    lines = (" ".join(line.split()) for line in "".join(extractor.parts).splitlines())
    text = "\n".join(line for line in lines if line)
    return " ".join("".join(extractor.title_parts).split()), text


def _host(url: str) -> str:
    return urlsplit(url).hostname or "unknown"


def make_web_fetch(resolver: Resolver = system_resolver) -> Tool:
    async def web_fetch(args: Args, ctx: ToolContext) -> ToolOutput:
        settings = ctx.settings
        response, body, final_url = await safe_get(
            ctx.http,
            args["url"],
            resolver=resolver,
            max_bytes=settings.web_fetch_max_bytes,
            timeout_s=settings.web_fetch_timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/json"},
        )
        if response.status_code >= 400:
            raise ToolError(f"The page returned an error ({response.status_code}).")
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith(TEXT_TYPES):
            raise ToolError(f"That is not a text page ({content_type}), so it cannot be read.")
        text = body.decode(response.encoding or "utf-8", errors="replace")
        title = ""
        if "html" in content_type or (not content_type and "<html" in text[:2000].lower()):
            title, text = html_to_text(text)
        host = _host(final_url)
        header = f"URL: {final_url}\n" + (f"Title: {title}\n" if title else "")
        return ToolOutput(
            text=f"{header}\n{text}".strip(),
            summary=f"Read {host}" + (f": {title[:80]}" if title else ""),
            source=f"web:{host}",
        )

    return Tool(
        name="web_fetch",
        description=(
            "Fetch a public web page and return its readable text. "
            "Use it to read a page you found or that the user gave you."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "An http or https URL", "maxLength": 2000}
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=web_fetch,
        summary=lambda args: f"Opened {_host(str(args.get('url', '')))}",
        read_only=True,
        timeout_seconds=30.0,
    )


async def _brave_search(args: Args, ctx: ToolContext) -> list[dict[str, Any]]:
    settings = ctx.settings
    try:
        response = await ctx.http.get(
            settings.search_api_url,
            params={"q": args["query"], "count": settings.search_result_count},
            headers={"X-Subscription-Token": settings.search_api_key, "Accept": "application/json"},
            timeout=settings.web_fetch_timeout_seconds,
        )
        response.raise_for_status()
        results = response.json().get("web", {}).get("results", [])
    except (httpx.HTTPError, ValueError, AttributeError) as error:
        raise ToolError("Web search failed. Try again later.") from error
    return [
        {
            "title": str(item.get("title", "")),
            "url": str(item.get("url", "")),
            "snippet": str(item.get("description", "")),
        }
        for item in results
        if isinstance(item, dict)
    ]


SEARCH_PROVIDERS = {"brave": _brave_search}


async def _web_search(args: Args, ctx: ToolContext) -> ToolOutput:
    """One function in front of whichever search provider is configured."""
    settings = ctx.settings
    provider = SEARCH_PROVIDERS.get(settings.search_provider)
    if provider is None or not settings.search_api_key:
        raise ToolError(
            "Web search is not set up on this server. "
            "If you know a likely URL, use web_fetch instead."
        )
    results = await provider(args, ctx)
    if not results:
        return ToolOutput("No results.", "No results", source="search")
    lines = [
        f"{index}. {item['title']}\n   {item['url']}\n   {item['snippet']}"
        for index, item in enumerate(results, start=1)
    ]
    return ToolOutput("\n".join(lines), f"{len(results)} results", source="search")


def make_web_search() -> Tool:
    return Tool(
        name="web_search",
        description="Search the web. Returns titles, URLs and short snippets.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 400}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_web_search,
        summary=lambda args: f"Searched the web for {str(args.get('query', ''))[:80]!r}",
        read_only=True,
        timeout_seconds=20.0,
    )
