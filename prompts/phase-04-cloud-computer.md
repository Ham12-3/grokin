# Phase 4: Cloud computer and live screen

Build phase 4 only. Read `docs/07-cloud-computer.md` and `docs/04-desktop-tauri.md` (Live screen panel).

## Build

1. `infra/computer/Dockerfile` (start from `templates/computer.Dockerfile`) and `start.sh`: Xvfb displays :1 to :6, Fluxbox, Chromium with persistent profile and remote debugging per display, x11vnc + websockify per display, the control server on port 7000 with a token.
2. Migration: `computers`.
3. `ComputerProvider` protocol + `DockerProvider` (docker SDK for Python): one container per user, named volumes for `/workspace` and the Chromium profile, CPU/memory limits, no published ports to the host network except through the API proxy.
4. Stub `E2BProvider` with the same interface and clear TODOs (implement fully if E2B keys are set and you are confident; otherwise leave it for later).
5. Display allocation in Redis per user. Release on run end.
6. Move the files tools to the computer (`/workspace`). Add `terminal_run`, `browser_open`, `browser_read`, `browser_click`, `browser_type`, `browser_screenshot` (Playwright `connect_over_cdp`), `request_takeover`.
7. `POST /computer/start|stop`, `GET /computer`, `computer.status` events. Auto-pause after `COMPUTER_IDLE_MINUTES`.
8. WebSocket VNC proxy `/computer/{id}/vnc?bot_id=` with token + ownership check, piping to the right websockify port.
9. `POST /runs/{id}/pause` and `/resume`.

## Desktop

1. Screen tab in the details pane using `@novnc/novnc`, view-only by default.
2. Take over / Give back buttons (pause/resume the run, switch noVNC to interactive).
3. Takeover card in chat with "Open screen".
4. Computer status in Settings with Start/Stop/Restart.

## Done means

- First message that needs the browser starts the computer ("Starting your computer...") and then the Bot opens a site.
- You watch it live in the Screen tab.
- "Go to github.com and sign in" leads to a takeover card; you sign in yourself; Give back; the Bot continues.
- Restart the computer: files in `/workspace` and the GitHub login are still there.
- Another test user cannot open your VNC URL.
- All checks pass (computer integration tests marked `slow` may be skipped in CI).

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
