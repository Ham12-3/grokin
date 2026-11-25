"""Client for the control server inside a computer. Shared by every hosted provider."""

from typing import Any
from urllib.parse import quote

import httpx

from crew.computer.provider import ComputerError, ComputerHandle, ExecResult, FileEntry

UNREACHABLE = "Your computer is not responding. Try again in a moment."


class ControlBackedProvider:
    """Implements commands, files, screens and browser actions over the control server."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        handle: ComputerHandle,
        method: str,
        path: str,
        *,
        timeout_s: float = 60.0,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await self._http.request(
                method,
                f"{handle.base_url}{path}",
                headers={"X-Control-Token": handle.token},
                timeout=timeout_s,
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise ComputerError(UNREACHABLE) from error
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("detail", ""))
            except ValueError:
                detail = ""
            raise ComputerError(
                detail[:400] or f"The computer returned an error ({response.status_code})."
            )
        return response

    async def healthy(self, base_url: str) -> bool:
        try:
            response = await self._http.get(f"{base_url}/health", timeout=3.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def token_accepted(self, handle: ComputerHandle) -> bool:
        try:
            response = await self._http.get(
                f"{handle.base_url}/files/list",
                params={"path": "."},
                headers={"X-Control-Token": handle.token},
                timeout=5.0,
            )
        except httpx.HTTPError:
            return False
        return response.status_code != 401

    async def exec(
        self, handle: ComputerHandle, cmd: str, timeout_s: float, display: int | None = None
    ) -> ExecResult:
        response = await self._request(
            handle,
            "POST",
            "/exec",
            json={"cmd": cmd, "timeout": timeout_s, "display": display},
            timeout_s=timeout_s + 15,
        )
        body = response.json()
        return ExecResult(
            exit_code=body.get("exit_code"),
            stdout=str(body.get("stdout", "")),
            stderr=str(body.get("stderr", "")),
            timed_out=bool(body.get("timed_out")),
        )

    async def read_file(self, handle: ComputerHandle, path: str) -> bytes:
        response = await self._request(handle, "GET", "/files", params={"path": path})
        return response.content

    async def write_file(self, handle: ComputerHandle, path: str, data: bytes) -> None:
        await self._request(handle, "PUT", "/files", params={"path": path}, content=data)

    async def list_dir(self, handle: ComputerHandle, path: str) -> list[FileEntry]:
        response = await self._request(handle, "GET", "/files/list", params={"path": path})
        return [
            FileEntry(str(item["name"]), bool(item["is_dir"]), int(item["size"]))
            for item in response.json()
        ]

    async def start_display(self, handle: ComputerHandle, display: int) -> None:
        await self._request(handle, "POST", f"/displays/{display}/start", timeout_s=60.0)

    async def browser(
        self, handle: ComputerHandle, display: int, action: str, **args: Any
    ) -> dict[str, Any]:
        response = await self._request(
            handle, "POST", f"/browser/{display}", json={"action": action, **args}, timeout_s=75.0
        )
        body: dict[str, Any] = response.json()
        return body

    def vnc_url(self, handle: ComputerHandle, display: int) -> str:
        base = handle.base_url.replace("http://", "ws://").replace("https://", "wss://")
        return f"{base}/vnc/{display}?token={quote(handle.token)}"
