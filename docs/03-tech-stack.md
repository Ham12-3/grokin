# 03. Tech stack

## Desktop

| Need | Choice | Notes |
|---|---|---|
| Shell | Tauri 2 | Small installers, uses the OS webview. Rust core for native features. |
| UI | React 18 + TypeScript + Vite | Static build (Tauri serves files, no SSR, so no Next.js). |
| Styling | Tailwind + shadcn/ui | Dark and light themes. |
| Server state | TanStack Query | Caching, retries, optimistic updates. |
| Client state | Zustand | Current chat, panes, composer drafts. |
| Routing | TanStack Router or React Router | File-based not needed. |
| Live screen | `@novnc/novnc` | VNC over WebSocket inside a panel. |
| Markdown | `react-markdown` + `rehype-sanitize` | Always sanitize AI output. |
| Icons | `lucide-react` | |

### Tauri plugins and crates

| Job | Plugin / crate |
|---|---|
| Login redirect into the app | `tauri-plugin-deep-link` (`crew://auth?code=...`) |
| Send the deep link to the already open app | `tauri-plugin-single-instance` |
| Store tokens in the OS keychain | `keyring` crate |
| Small local settings | `tauri-plugin-store` |
| Desktop alerts | `tauri-plugin-notification` |
| Start at login | `tauri-plugin-autostart` |
| Remember window size | `tauri-plugin-window-state` |
| Quick open shortcut | `tauri-plugin-global-shortcut` |
| Open links in the browser | `tauri-plugin-opener` |
| Auto-update | `tauri-plugin-updater` |
| Logs | `tauri-plugin-log` |
| Local bridge helper (later) | `tauri-plugin-shell` with a sidecar |

## Backend

| Need | Choice | Notes |
|---|---|---|
| API | FastAPI | REST + WebSocket. OpenAPI schema drives the TS client. |
| Validation | Pydantic v2 | |
| DB access | SQLAlchemy 2 async + asyncpg | |
| Migrations | Alembic | |
| Database | Postgres 16 + pgvector | Memory search later. |
| Queue | Redis 7 + ARQ | Async jobs, retries, cron. Swap to Temporal or Inngest later if needed. |
| Realtime | Redis pub/sub -> FastAPI WebSocket | One channel per chat and one per user. |
| Auth | Email magic link + Google OAuth, JWT access (15 min) + refresh (30 days) | Refresh token lives in the OS keychain. |
| LLM | `anthropic` Python SDK, tool use, streaming | Model from `CREW_MODEL` env var. |
| MCP | `mcp` Python SDK (client) | For connectors and custom MCP URLs. |
| OAuth connectors | Composio (or Nango) | Saves weeks of token handling. |
| Secrets | `cryptography` AES-256-GCM, data key wrapped by AWS KMS (prod) or `VAULT_MASTER_KEY` (dev) | |
| Web search | Any search API (Brave, Tavily, Exa) behind one `search()` tool | Key from env. |
| Observability | `structlog` JSON logs, OpenTelemetry, Sentry | Log tool calls, never secrets. |

## Cloud computer

| Env | Choice |
|---|---|
| Local dev | Docker container per user: Ubuntu, Xvfb, Fluxbox, Chromium, x11vnc, websockify, Playwright, a small control server (FastAPI) |
| Production | E2B desktop sandboxes (pause and resume keeps the disk), or self-hosted Firecracker later |

Both sit behind one interface, `ComputerProvider` (see `07-cloud-computer.md`).

## Tooling

- pnpm, uv, cargo
- Ruff + mypy (Python), ESLint + Prettier + `tsc --noEmit` (TS), clippy + rustfmt (Rust)
- Pytest, Vitest, Playwright (desktop UI smoke tests against the Vite dev server)
- GitHub Actions with `tauri-action` for builds on macOS, Windows and Linux
