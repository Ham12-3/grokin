# 07. Cloud computer

Each user gets ONE persistent Linux machine. All their Bots share it (files, browser cookies, signed-in sessions). Each Bot gets its own screen (display) so two Bots can work at once.

## Provider interface (`services/shared/crew/computer/provider.py`)

```python
class ComputerProvider(Protocol):
    async def ensure(self, user_id: str) -> ComputerHandle: ...      # create or resume
    async def stop(self, handle: ComputerHandle) -> None: ...        # pause, keep disk
    async def exec(self, handle, cmd: str, timeout: int, display: int | None = None) -> ExecResult: ...
    async def read_file(self, handle, path: str) -> bytes: ...
    async def write_file(self, handle, path: str, data: bytes) -> None: ...
    async def list_dir(self, handle, path: str) -> list[FileEntry]: ...
    async def cdp_url(self, handle, display: int) -> str: ...        # Chrome DevTools for Playwright
    async def vnc_target(self, handle, display: int) -> str: ...     # host:port for websockify
```

Two implementations:

- `DockerProvider` (local dev): one container per user from `infra/computer/Dockerfile`, a named Docker volume mounted at `/workspace` and `/home/crew/.config/chromium` so files and logins survive restarts.
- `E2BProvider` (production): E2B desktop sandbox per user. Pause when idle, resume on the next run, so the disk and browser profile persist.

Pick with `COMPUTER_PROVIDER=docker|e2b`.

## Inside the machine

- Ubuntu 24.04, user `crew` (not root)
- Xvfb displays `:1` to `:6` (one per active Bot, assigned by the worker), Fluxbox window manager
- Chromium with a persistent profile, remote debugging on `127.0.0.1:92xx` per display
- x11vnc per display + websockify on `60xx`
- Python 3, Node, git, ripgrep, jq, ffmpeg, Playwright
- `/workspace` (durable work) and `/workspace/outputs` (things for the Library)
- A tiny control server (FastAPI on port 7000) that runs commands and file operations, protected by a per-computer token

## Display assignment

- When a run starts, the worker asks Redis for a free display for that user (`computer:{user}:displays`).
- The display is linked to the Bot for the run, and released when the run ends.
- The live screen panel connects to the display of the Bot that is currently working.

## Browser control

- Playwright connects over CDP (`chromium.connect_over_cdp`).
- Tools return a short text view of the page (title, URL, main text, list of clickable elements with ids) plus an optional screenshot.
- For tricky pages the Bot can use Claude's computer use tool with screenshots and clicks on its display.

## Take over

1. Bot calls `request_takeover("Please sign in to LinkedIn")`.
2. Run goes to `paused`, the user gets a notification and a card with "Open screen".
3. The user signs in through the live screen (interactive mode).
4. The user clicks "Give back", the run resumes.

Passwords typed by the user go straight to the VM through VNC. They are never sent to the LLM or stored in logs.

## Security

- Each user's machine is isolated (separate container or sandbox, separate volume, no shared network namespace).
- No inbound ports open to the internet. The API proxies VNC after checking ownership.
- The machine never receives the user's API keys. Tools that need secrets run through the backend tool proxy, which injects them at the last moment.
- Outbound network allowed (Bots browse the web), but block cloud metadata IPs (169.254.169.254) and private ranges.
- CPU, memory and disk limits per machine. Kill commands after their timeout.

## Cost control

- Pause the machine after 10 minutes with no runs (configurable).
- Resume automatically when a run or routine starts.
- Show machine status (running, paused, starting) in the app.
