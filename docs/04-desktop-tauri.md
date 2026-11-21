# 04. Desktop app (Tauri 2)

## Two halves

- **React frontend (webview):** all screens. Talks to the backend over HTTPS and WebSocket.
- **Rust core:** only OS jobs. Keychain, deep links, tray, notifications, auto-update, autostart, global shortcut, and later the local bridge.

Frontend to Rust: `invoke("command", args)`. Rust to frontend: `app.emit("event", payload)`.

Wrap every `invoke` in `src/lib/tauri.ts` with typed functions. Never call `invoke` with a string directly from a component.

## Rust commands (all must be in capabilities)

| Command | What it does |
|---|---|
| `auth_start_login(provider)` | Opens the system browser to `{API}/auth/{provider}/start?redirect=crew://auth` |
| `auth_get_tokens()` | Reads the refresh token from the keychain, returns `{has_session}` (never returns the refresh token itself to JS) |
| `auth_get_access_token()` | Uses the refresh token to get a fresh access token from the API and returns it (access token is short-lived, fine in JS memory) |
| `auth_logout()` | Calls the API logout, deletes keychain entries |
| `notify(title, body, route)` | Shows a desktop notification; clicking it focuses the window and emits `navigate` with `route` |
| `set_tray_badge(count)` | Pending approvals count in the tray tooltip |
| `app_version()` | For the settings screen |

Keychain service name: `crew`, entries: `refresh_token`, `device_id`.

## Login flow

1. User clicks "Sign in with Google" or enters email for a magic link.
2. Rust opens the system browser to the API start URL.
3. After login, the API redirects to `crew://auth?code=ONE_TIME_CODE`.
4. `deep-link` catches it. `single-instance` makes sure it reaches the running app (needed on Windows and Linux).
5. Rust exchanges the code at `POST /auth/exchange` for `{access_token, refresh_token}`.
6. Rust stores the refresh token in the keychain and emits `auth:changed`.
7. The frontend calls `auth_get_access_token()` when it needs a token and keeps it in memory only.

The one-time code expires in 60 seconds and works once. Use PKCE (`code_verifier` kept in Rust memory).

## WebSocket

- URL: `wss://{API}/ws?token={access_token}`. The server checks the token on connect.
- One connection per app. Subscribe with `{type:"subscribe", chat_id}` messages.
- Reconnect with backoff (1s, 2s, 4s, max 30s). On reconnect, refetch the open chat so nothing is missed.
- Keep the connection in the frontend. When the user closes the window, hide it to the tray (do not quit) so the connection and notifications keep working.

## Notifications

When these events arrive and the window is hidden or not focused, call `notify`:

- `approval.created`: "Inbox Bot wants to send an email"
- `run.failed`
- `routine.completed` (only if the routine has `notify=true`)

## Tray

Menu: Open Crew, New chat, Pending approvals (n), Pause all routines, Quit.

## Live screen panel

- Uses `@novnc/novnc` (RFB client) inside a resizable right-side panel.
- Connects to `wss://{API}/computer/{computer_id}/vnc?token=...&bot_id=...`. The API proxies to the VM's websockify port after checking the user owns the computer.
- View-only by default. A "Take over" button switches to interactive and tells the Bot to pause (`POST /runs/{id}/pause`). "Give back" resumes.

## Capabilities (security)

`src-tauri/capabilities/default.json` allows only the commands above and these plugin permissions: `deep-link:default`, `notification:default`, `store:default`, `opener:default`, `updater:default`, `window-state:default`, `global-shortcut:default`, `autostart:default`, `log:default`. No `fs` or `shell` for the main window.

Content Security Policy in `tauri.conf.json`:

```
default-src 'self';
connect-src 'self' https://api.crew.local wss://api.crew.local http://localhost:8000 ws://localhost:8000;
img-src 'self' data: https:;
style-src 'self' 'unsafe-inline';
script-src 'self';
frame-src 'none';
```

Replace the API hosts with yours. Render all AI output through `react-markdown` with `rehype-sanitize`; never `dangerouslySetInnerHTML`.

## Local bridge (phase 11, optional)

Lets a Bot read files or run commands on the user's own computer.

- Rust commands `bridge_read_file`, `bridge_list_dir`, `bridge_run`.
- Only inside folders the user picked in settings.
- Every call shows a native dialog: Allow once, Always allow for this folder, Deny.
- The backend asks for it through the WebSocket (`bridge.request`), the app answers with `bridge.response`. If the app is offline, the tool returns "local computer not available".

## Packaging

- Windows: NSIS installer. macOS: `.dmg`. Linux: AppImage and `.deb`.
- Updater: generate keys with `pnpm tauri signer generate`. Public key in `tauri.conf.json`, private key in GitHub secrets. Losing it means existing users cannot update.
- OS code signing is separate: Apple Developer ID + notarization, and a Windows code signing certificate.
