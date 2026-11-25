"""SSRF guard for anything that fetches a URL the model chose.

Rules: http and https only, no credentials in the URL, and every address the host resolves
to must be a public internet address. The request then goes to the checked address itself
(with the original Host header and TLS name), so a second DNS answer cannot redirect it.
Redirects are followed by hand and each hop is checked again.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from crew.tools.registry import ToolError

Resolver = Callable[[str, int], Awaitable[list[str]]]

MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ToolError(f"Could not find the site {host}.") from error
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # `is_global` is false for private, loopback, link-local (cloud metadata), shared,
    # reserved, multicast and unspecified ranges.
    return ip.is_global and not ip.is_multicast


@dataclass(frozen=True)
class Target:
    url: str  # the original URL, for display
    host: str
    connect_url: str  # same URL with the checked IP in place of the host
    host_header: str
    scheme: str


async def check_url(url: str, resolver: Resolver) -> Target:
    """Validates a URL and pins it to one public address, or raises ToolError."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise ToolError("That is not a valid URL.") from error
    if parts.scheme not in ("http", "https"):
        raise ToolError("Only http and https URLs can be fetched.")
    if parts.username or parts.password:
        raise ToolError("URLs with a username or password are not allowed.")
    host = parts.hostname
    if not host:
        raise ToolError("That is not a valid URL.")

    default_port = 443 if parts.scheme == "https" else 80
    try:
        # A literal address is checked as it is: no resolver gets a say.
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = await resolver(host, port or default_port)
    if not addresses or not all(is_public_address(address) for address in addresses):
        raise ToolError("That address is not on the public internet, so it is blocked.")

    address = addresses[0]
    literal = f"[{address}]" if ":" in address else address
    netloc = f"{literal}:{port}" if port else literal
    host_header = f"{host}:{port}" if port else host
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return Target(url, host, f"{parts.scheme}://{netloc}{path}{query}", host_header, parts.scheme)


async def safe_get(
    http: httpx.AsyncClient,
    url: str,
    *,
    resolver: Resolver,
    max_bytes: int,
    timeout_s: float,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Response, bytes, str]:
    """GETs a URL through the guard. Returns the response, the body (capped) and the final URL."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        target = await check_url(current, resolver)
        request = http.build_request(
            "GET",
            target.connect_url,
            headers={**(headers or {}), "Host": target.host_header},
            extensions={"sni_hostname": target.host} if target.scheme == "https" else {},
            timeout=timeout_s,
        )
        try:
            response = await http.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as error:
            raise ToolError(f"Could not reach {target.host}.") from error
        try:
            if response.status_code in REDIRECT_STATUSES and "location" in response.headers:
                current = urljoin(current, response.headers["location"])
                continue
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= max_bytes:
                    break
            return response, b"".join(chunks)[:max_bytes], current
        except httpx.HTTPError as error:
            raise ToolError(f"Could not read the page from {target.host}.") from error
        finally:
            await response.aclose()
    raise ToolError("Too many redirects.")
