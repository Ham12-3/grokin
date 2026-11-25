"""Control server inside the Crew computer.

The only door into the machine: one port (7000), every request checked against
CONTROL_TOKEN. It runs commands, reads and writes files under /workspace, starts a screen
(Xvfb + window manager + Chromium + VNC) per display on demand, drives the browser with
Playwright over CDP, and bridges VNC to a WebSocket for the live screen.

Chromium's debugging port and the VNC port listen on localhost only and are never
published: the backend reaches them through this server.
"""

import asyncio
import base64
import contextlib
import glob
import hmac
import os
import signal
import time
from pathlib import Path, PurePosixPath
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket
from playwright.async_api import Browser, Page, Playwright, async_playwright
from pydantic import BaseModel, Field

TOKEN = os.environ["CONTROL_TOKEN"]
WORKSPACE = Path("/workspace")
DISPLAYS = range(1, 7)
OUTPUT_CAP = 200_000
SCREEN = "1280x800x24"
FILE_MAX_BYTES = 20_000_000

app = FastAPI(title="Crew computer control", docs_url=None, redoc_url=None, openapi_url=None)

_display_locks = {n: asyncio.Lock() for n in DISPLAYS}
_display_processes: dict[int, list[asyncio.subprocess.Process]] = {}
_browsers: dict[int, Browser] = {}
_playwright: Playwright | None = None


# --- Auth -------------------------------------------------------------------------------


def _token_ok(candidate: str | None) -> bool:
    return candidate is not None and hmac.compare_digest(candidate, TOKEN)


def require_token(x_control_token: str | None = Header(default=None)) -> None:
    if not _token_ok(x_control_token):
        raise HTTPException(status_code=401, detail="unauthorized")


def _display(n: int) -> int:
    if n not in DISPLAYS:
        raise HTTPException(status_code=400, detail="display must be 1 to 6")
    return n


# --- Files ------------------------------------------------------------------------------


def _resolve(path: str) -> Path:
    cleaned = path.replace("\\", "/").strip()
    if cleaned.startswith("/workspace"):
        cleaned = cleaned[len("/workspace") :]
    relative = PurePosixPath(cleaned.lstrip("/") or ".")
    if ".." in relative.parts:
        raise HTTPException(status_code=400, detail="That path is outside your workspace.")
    target = (WORKSPACE / relative).resolve()
    # resolve() follows symlinks, so a link pointing outside is caught here too.
    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise HTTPException(status_code=400, detail="That path is outside your workspace.")
    return target


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", "displays": sorted(_display_processes)}


@app.get("/files", dependencies=[Depends(require_token)])
async def read_file(path: str = Query(...)) -> Response:
    target = _resolve(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"There is no file at {path}.")
    if target.stat().st_size > FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="That file is too large to read.")
    return Response(await asyncio.to_thread(target.read_bytes), media_type="application/octet-stream")


@app.put("/files", dependencies=[Depends(require_token)])
async def write_file(request: Request, path: str = Query(...)) -> dict[str, int]:
    target = _resolve(path)
    if target == WORKSPACE or target.is_dir():
        raise HTTPException(status_code=400, detail="That path is a folder, not a file.")
    data = await request.body()
    if len(data) > FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="That file is too large.")

    def _write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    await asyncio.to_thread(_write)
    return {"size": len(data)}


@app.get("/files/list", dependencies=[Depends(require_token)])
async def list_dir(path: str = Query(default=".")) -> list[dict[str, object]]:
    target = _resolve(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"There is no folder at {path}.")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"{path} is a file, not a folder.")
    children = sorted(target.iterdir(), key=lambda item: item.name.lower())
    return [
        {
            "name": child.name,
            "is_dir": child.is_dir(),
            "size": child.stat().st_size if child.is_file() else 0,
        }
        for child in children
    ]


# --- Commands ---------------------------------------------------------------------------


class ExecRequest(BaseModel):
    cmd: str = Field(min_length=1, max_length=20_000)
    timeout: float = Field(default=60, gt=0, le=1800)
    display: int | None = None


async def _read_capped(stream: asyncio.StreamReader | None) -> str:
    """Reads everything (so the process never blocks on a full pipe) but keeps only the cap."""
    if stream is None:
        return ""
    kept = bytearray()
    while chunk := await stream.read(65536):
        if len(kept) < OUTPUT_CAP:
            kept.extend(chunk[: OUTPUT_CAP - len(kept)])
    return kept.decode("utf-8", errors="replace")


@app.post("/exec", dependencies=[Depends(require_token)])
async def exec_command(body: ExecRequest) -> dict[str, object]:
    env = {**os.environ, "HOME": "/home/crew", "TERM": "dumb"}
    env.pop("CONTROL_TOKEN", None)  # commands never see the control token
    if body.display is not None:
        await ensure_display(_display(body.display))
        env["DISPLAY"] = f":{body.display}"
    process = await asyncio.create_subprocess_exec(
        "bash",
        "-lc",
        body.cmd,
        cwd=WORKSPACE,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # its own process group, so a timeout kills children too
    )
    out_task = asyncio.create_task(_read_capped(process.stdout))
    err_task = asyncio.create_task(_read_capped(process.stderr))
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), body.timeout)
    except TimeoutError:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
    stdout, stderr = await asyncio.gather(out_task, err_task)
    return {
        "exit_code": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
    }


# --- Displays ---------------------------------------------------------------------------


def _chromium_binary() -> str:
    matches = glob.glob("/opt/ms-playwright/chromium-*/chrome-linux*/chrome")
    if not matches:
        raise HTTPException(status_code=500, detail="Chromium is not installed in this image.")
    return sorted(matches)[-1]


async def _spawn(n: int, *args: str) -> asyncio.subprocess.Process:
    env = {**os.environ, "DISPLAY": f":{n}", "HOME": "/home/crew"}
    env.pop("CONTROL_TOKEN", None)
    process = await asyncio.create_subprocess_exec(
        *args,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    _display_processes.setdefault(n, []).append(process)
    return process


async def _wait_for(check: Any, seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if await check():
            return
        await asyncio.sleep(0.1)
    raise HTTPException(status_code=500, detail=f"{what} did not start in time.")


async def _port_open(port: int) -> bool:
    try:
        _, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        return False
    writer.close()
    return True


def _alive(n: int) -> bool:
    processes = _display_processes.get(n, [])
    return bool(processes) and all(process.returncode is None for process in processes)


async def ensure_display(n: int) -> None:
    """Starts Xvfb, the window manager, VNC and Chromium for display `n`, once."""
    async with _display_locks[n]:
        if _alive(n):
            return
        await stop_display(n)
        socket = Path(f"/tmp/.X11-unix/X{n}")  # noqa: S108
        with contextlib.suppress(FileNotFoundError):
            Path(f"/tmp/.X{n}-lock").unlink()  # noqa: S108
        await _spawn(n, "Xvfb", f":{n}", "-screen", "0", SCREEN, "-nolisten", "tcp")

        async def x_ready() -> bool:
            return socket.exists()

        await _wait_for(x_ready, 10, "The screen")
        await _spawn(n, "fluxbox")
        await _spawn(
            n, "x11vnc", "-display", f":{n}", "-rfbport", str(5900 + n),
            "-localhost", "-nopw", "-forever", "-shared", "-quiet", "-noxdamage",
        )  # fmt: skip
        profile = Path(f"/home/crew/.config/chromium-{n}")
        profile.mkdir(parents=True, exist_ok=True)
        # A crashed browser leaves lock files that stop the next start.
        for leftover in profile.glob("Singleton*"):
            with contextlib.suppress(OSError):
                leftover.unlink()
        await _spawn(
            n, _chromium_binary(),
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={9220 + n}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run", "--no-default-browser-check", "--disable-dev-shm-usage",
            "--password-store=basic", "--start-maximized", "--window-position=0,0",
            "--window-size=1280,800",
            # A stopped computer kills the browser; do not greet the user with "Restore pages?".
            "--hide-crash-restore-bubble",
            # The container itself is the sandbox: Chromium's own needs kernel features
            # Docker does not allow for an unprivileged user.
            "--no-sandbox",
            "about:blank",
        )  # fmt: skip

        async def ports_ready() -> bool:
            return await _port_open(5900 + n) and await _port_open(9220 + n)

        await _wait_for(ports_ready, 30, "The browser")


async def stop_display(n: int) -> None:
    browser = _browsers.pop(n, None)
    if browser is not None:
        with contextlib.suppress(Exception):
            await browser.close()
    for process in reversed(_display_processes.pop(n, [])):
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
    await asyncio.sleep(0)


@app.post("/displays/{n}/start", dependencies=[Depends(require_token)])
async def start_display(n: int) -> dict[str, object]:
    await ensure_display(_display(n))
    return {"display": n, "status": "running"}


# --- Browser ----------------------------------------------------------------------------

_SNAPSHOT = """
() => {
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  document.querySelectorAll('[data-crew-id]').forEach((el) => el.removeAttribute('data-crew-id'));
  const selector = 'a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=tab],[role=menuitem]';
  const elements = [...document.querySelectorAll(selector)].filter(visible).slice(0, 120);
  elements.forEach((el, index) => el.setAttribute('data-crew-id', String(index + 1)));
  const label = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
  return {
    title: document.title,
    url: location.href,
    text: (document.body ? document.body.innerText : '').slice(0, 20000),
    elements: elements.map((el, index) => ({
      id: index + 1,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      label: label(el),
    })),
  };
}
"""


class BrowserRequest(BaseModel):
    action: str
    url: str | None = Field(default=None, max_length=4000)
    element: int | None = None
    text: str | None = Field(default=None, max_length=20_000)
    press_enter: bool = False


async def _page(n: int) -> Page:
    global _playwright
    await ensure_display(n)
    if _playwright is None:
        _playwright = await async_playwright().start()
    browser = _browsers.get(n)
    if browser is None or not browser.is_connected():
        browser = await _playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{9220 + n}")
        _browsers[n] = browser
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    # The newest tab is the one the Bot is working in (a click may have opened it).
    return context.pages[-1] if context.pages else await context.new_page()


async def _settle(page: Page) -> None:
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    await asyncio.sleep(0.3)


@app.post("/browser/{n}", dependencies=[Depends(require_token)])
async def browser_action(n: int, body: BrowserRequest) -> dict[str, object]:
    page = await _page(_display(n))
    try:
        if body.action == "open":
            if not body.url or not body.url.lower().startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail="Only http and https URLs can be opened.")
            await page.goto(body.url, wait_until="domcontentloaded", timeout=30_000)
            await _settle(page)
        elif body.action in ("click", "type"):
            if body.element is None:
                raise HTTPException(status_code=400, detail="An element id is required.")
            target = page.locator(f'[data-crew-id="{int(body.element)}"]').first
            if await target.count() == 0:
                raise HTTPException(
                    status_code=404,
                    detail="That element is not on the page any more. Read the page again.",
                )
            if body.action == "click":
                await target.click(timeout=10_000)
            else:
                await target.fill(body.text or "", timeout=10_000)
                if body.press_enter:
                    await target.press("Enter")
            await _settle(page)
            page = await _page(n)
        elif body.action == "screenshot":
            folder = WORKSPACE / "outputs" / "screenshots"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"screen-{int(time.time() * 1000)}.png"
            await page.screenshot(path=str(path))
            return {"path": str(path), "size": path.stat().st_size, "url": page.url}
        elif body.action != "read":
            raise HTTPException(status_code=400, detail="Unknown browser action.")
        snapshot: dict[str, object] = await page.evaluate(_SNAPSHOT)
        return snapshot
    except HTTPException:
        raise
    except Exception as error:
        # Playwright errors can be long; the first line says what happened.
        message = str(error).strip().splitlines()[0][:300] if str(error).strip() else "failed"
        raise HTTPException(status_code=502, detail=f"The browser could not do that: {message}") from error


# --- Live screen ------------------------------------------------------------------------


@app.websocket("/vnc/{n}")
async def vnc(websocket: WebSocket, n: int, token: str | None = None) -> None:
    """Bridges a WebSocket to the display's VNC port (what websockify would do)."""
    if not _token_ok(token) or n not in DISPLAYS:
        await websocket.close(code=4401)
        return
    await ensure_display(n)
    reader, writer = await asyncio.open_connection("127.0.0.1", 5900 + n)
    offered = websocket.scope.get("subprotocols", [])
    await websocket.accept(subprotocol="binary" if "binary" in offered else None)

    async def to_client() -> None:
        while data := await reader.read(65536):
            await websocket.send_bytes(data)

    async def to_vnc() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes") or (message.get("text") or "").encode()
            if data:
                writer.write(data)
                await writer.drain()

    tasks = [asyncio.create_task(to_client()), asyncio.create_task(to_vnc())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        with contextlib.suppress(Exception):
            await websocket.close()


@app.get("/screenshot/{n}", dependencies=[Depends(require_token)])
async def screenshot(n: int) -> dict[str, str]:
    """A PNG of the whole display, for checks and thumbnails."""
    page = await _page(_display(n))
    return {"png_base64": base64.b64encode(await page.screenshot()).decode()}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7000, log_level="warning")  # noqa: S104
