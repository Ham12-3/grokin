# 12. Testing and release

## Tests

| Layer | Tool | Must cover |
|---|---|---|
| Python unit | pytest + pytest-asyncio | Agent loop with FakeLLM, approval policy, vault crypto, risk functions, SSRF guard, cron next-run maths |
| Python API | httpx AsyncClient + test Postgres (testcontainers or the compose DB) | Auth, cross-user access on every router, WebSocket auth and subscribe checks |
| Worker | ARQ in-process | Run lifecycle, resume after approval, budget stop, routine scheduling |
| Computer | Docker provider integration test (marked `slow`) | Start, exec, file round trip, CDP connect, persistence after restart |
| Frontend | Vitest + Testing Library | Composer (`/` and `@` pickers), approval card actions, WS reducer |
| E2E | Playwright against the Vite dev server with a mocked Tauri `invoke` | Sign in (mocked), chat, approval approve flow |
| Rust | cargo test | Deep link parsing, keychain wrapper (mock backend) |

Never call the real Anthropic API in CI. Use FakeLLM. Keep one manual "live" smoke script (`scripts/smoke_live.py`) for local use only.

## CI (GitHub Actions)

- `ci.yml` on every push: ruff, mypy, pytest (with Postgres + Redis services), pnpm lint/typecheck/test, cargo clippy/test.
- `release.yml` on tags `v*`: `tauri-apps/tauri-action` matrix on `windows-latest`, `macos-latest` (universal), `ubuntu-22.04`. Uploads installers and `latest.json` for the updater to a GitHub Release.

## Secrets needed in GitHub

- `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (updater)
- `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` (macOS signing + notarization)
- Windows signing certificate details (or Azure code signing settings)

## Updater

- `tauri.conf.json` -> `plugins.updater.endpoints`: `https://github.com/<you>/crew/releases/latest/download/latest.json`
- Check on start and every 6 hours. Show "Update ready, restart" in the tray and settings. Never force-restart while a chat is streaming.

## Backend deploy

- Containers for `api` and `worker` (same image, different command).
- Managed Postgres (with pgvector) and Redis.
- Run Alembic migrations before the new API version starts.
- Environment variables from `.env.example`, secrets from your cloud secret manager.
- Health checks: `/health` (API), worker heartbeat key in Redis.

## Versioning

Semantic versions. Desktop and backend share the major.minor. The API returns `min_desktop_version` in `/me`; older apps show "Please update".
