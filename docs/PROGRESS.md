# PROGRESS

Claude Code updates this file at the end of every phase.

## Current phase

Phase 2 (Bots + streaming chat): built, waiting for your hands-on check.

## Done

### Phase 0: scaffold

- Repo layout from `docs/02-architecture.md`, placed at the repo root. Modules that belong
  to later phases exist as one-line docstring stubs naming their phase.
- `infra/docker-compose.yml`: Postgres 16 + pgvector and Redis 7. MinIO sits behind the
  `storage` profile (see Known issues).
- `services/`: one uv project (Python 3.12) holding `api`, `worker` and `shared/crew`.
  - `crew/config.py`: pydantic-settings, reads the repo-root `.env`. Secrets hidden in repr.
  - `GET /api/v1/health` returns `{status, version, db, redis}` from real checks with a timeout.
  - Alembic (async) with migration `0001` enabling `vector` and `citext`.
  - ARQ `WorkerSettings` with a placeholder `ping` job.
- `apps/desktop/`: Tauri 2 + React 18 + TypeScript + Vite, Tailwind 4, shadcn/ui,
  ESLint + Prettier, Vitest. Window "Crew", min size 1000x680.
- Root `Makefile`, `.github/workflows/ci.yml`, `.env.example`, `.gitignore`, `.gitattributes`.

### Phase 1: desktop shell + sign-in

Backend

- Migration `0002`: `users`, `refresh_tokens` (with `device_id`), `audit_log`. All ids UUID v7.
- Routes under `/api/v1`: `POST /auth/email/start`, `GET /auth/google/start`,
  `GET /auth/callback`, `POST /auth/exchange`, `POST /auth/refresh`, `POST /auth/logout`,
  `GET /me`. Logic is in `crew/auth/` (service, tokens, google, mailer).
- Magic links: in dev the link is printed to the API log (`auth.magic_link`). With `SMTP_URL`
  set it is emailed. In prod a missing `SMTP_URL` stops the API from starting.
- One-time codes: Redis, 60 second TTL, read-and-delete so they work once. PKCE (S256) checked
  on exchange. Redis keys are a sha256 of the secret, never the secret.
- Access tokens: JWT HS256, 15 minutes. The API refuses to start if `JWT_SECRET` is shorter
  than 32 characters. Refresh tokens: 48 random bytes, only the sha256 is stored, rotated on
  every refresh. Replaying an old refresh token signs that device out.
- Every error is `{"error": {"code", "message"}}`. Validation errors name fields only and never
  echo submitted values. CORS allows only the desktop webview origins.
- `audit_log` rows for login, logout and refresh-token reuse.

Desktop (Rust)

- Plugins: deep-link (`crew://`), single-instance (forwards the link to the running app),
  store, notification, opener, window-state, log, autostart.
- `auth.rs`: PKCE verifier kept in memory, deep link handler exchanges the code, refresh token
  saved in the OS keychain (service `crew`), `auth:changed` / `auth:error` events.
  `auth_get_access_token` refreshes when needed and returns only the access token.
- `tray.rs`: tray icon with Open Crew and Quit. Closing the window hides it.
- Commands are declared in `build.rs`, so each needs its own `allow-...` line in
  `capabilities/default.json`. A test checks the two lists match.
- Content Security Policy from `docs/04-desktop-tauri.md` is set in `tauri.conf.json`.

Desktop (React)

- `src/lib/tauri.ts` typed wrappers; `src/lib/api/client.ts` adds the access token and retries
  once with a fresh one on 401; types generated into `src/lib/api/schema.d.ts`.
- Sign-in screen (email + Google), "Check your email" state, signed-in placeholder home with
  the name from `/me` and Sign out.

### Phase 2: Bots + streaming chat

Backend

- Migration `0003`: `bots`, `chats`, `chat_members`, `messages`, `runs`, `usage_daily`.
- Bots: create, edit, delete, Primary Bot (one per user; the first Bot becomes Primary;
  deleting the Primary promotes the oldest remaining Bot). Limit of 50 (`MAX_BOTS_PER_USER`).
  Creating a Bot creates its direct chat; deleting a Bot deletes that chat and its messages.
- Chats: `GET /chats`, `POST /chats` (one Bot only for now), `GET /chats/{id}/messages` with
  `before` + `limit` paging, `POST /chats/{id}/messages` which saves the message, creates a
  `queued` run, enqueues the ARQ job and returns `{message, run_id}`.
- Worker job `run_agent`: builds the system prompt from the Bot, streams from Claude (model
  from `CREW_MODEL`), publishes `message.delta` to Redis, saves the message, records tokens in
  `runs` and `usage_daily`. A failed run always ends as `failed` with a safe message.
- LLM behind one interface (`crew/llm`): `AnthropicLLM` and a scripted `FakeLLM`.
  `LLM_PROVIDER=fake` runs the whole app without an API key (refused in prod).
- WebSocket `/api/v1/ws`: auth on connect, subscribe/unsubscribe with ownership checks,
  forwards Redis events, ping/pong, closes when the access token expires.
- `/me` now returns `input_tokens_today` and `output_tokens_today`.

Desktop

- Layout: sidebar (Bots, Primary star, status dot, + menu), chat, collapsible details pane
  with six tabs (only Settings has content).
- New Bot dialog and Bot settings tab (edit, Make Primary, delete with confirm).
- Chat: paged history ("Load earlier messages", also loads when you scroll to the top),
  streaming reply, composer (Enter sends, Shift+Enter new line), sanitized markdown, links
  open in the system browser.
- `src/lib/ws.ts`: one WebSocket, backoff 1s to 30s, re-subscribes and refetches after a
  reconnect; "Reconnecting..." banner; Zustand store for live text.

## Next

- Phase 3: agent loop + tools (`prompts/phase-03-agent-loop.md`).

## Shortcuts taken (to revisit)

- Claude itself has not been called yet: no `ANTHROPIC_API_KEY` was set, so streaming was
  verified with `FakeLLM` only. First real run needs a check of `crew/llm/anthropic_llm.py`.
- Server-side refusal fallbacks (the Anthropic `fallbacks` beta) are not enabled; a refused
  request shows a short "can't help with that" reply. Decide when a key is available.
- No daily budget enforcement yet (usage is recorded and shown); it arrives with phase 3.
- The details pane tabs other than Settings are placeholders.
- Scrolling up to load older messages was not exercised in the running app (the paging API
  and the button are tested).
- The selected Bot is not remembered across restarts; the Primary Bot opens.

- shadcn/ui defaults (neutral colours, Geist font). `docs/10-ui-spec.md` asks for Inter and one
  accent colour; apply with the real layout in phase 2.
- `/me` returns the user and `daily_token_budget` only. Today's token usage arrives with
  `usage_daily` in phase 3.
- The magic link signs in on a plain GET. An email scanner that pre-opens links could use it
  up before the user clicks. Add a confirm step before real email goes out.
- The email sender (`SmtpMailer`) has not been run against a real mail server.
- No Rust test covers a successful token refresh (needs an HTTP stub). The backend tests and
  the manual run cover it.
- `infra/computer/start.sh` is a placeholder; the cloud computer image builds in phase 4.
- The integration tests skip locally when Postgres or Redis is down. CI sets
  `CREW_REQUIRE_SERVICES=1` so they fail there instead.

## Known issues

- After an outage the app can take up to about 30 seconds to reconnect once the API is back,
  because of the reconnect backoff in the spec.
- A run whose worker dies stays `running` until `RUN_TIMEOUT_SECONDS` (10 minutes); the chat
  is blocked for that long.

- MinIO: `minio/minio` can no longer be pulled from Docker Hub (or quay.io), so the template's
  compose file made `make up` fail. MinIO is now behind the `storage` profile. Pick an object
  store before phase 9 (Library).
- CI has not run yet: the repo has no GitHub remote.
- Linux keychain support (`sync-secret-service`) is compiled in but untested; CI will need
  `libdbus-1-dev`.
- In dev the app registers the `crew://` link handler for your Windows user at start-up.
- `make` works from Git Bash on this machine; it may not be on the PowerShell PATH.

## Decisions log

| Date | Decision | Why |
|---|---|---|
| 2026-11-21 | Health lives at `/api/v1/health` | `docs/05` sets the base URL; `docs/11` said `/health`. |
| 2026-11-21 | `services/` is one installable uv project (hatchling, `dev-mode-dirs`) | Lets `api`, `worker` and `crew` import each other with the commands in `CLAUDE.md`. |
| 2026-11-21 | React pinned to 18 (template shipped 19) | The stack in `START_PROMPT.md` says React 18. |
| 2026-11-21 | Makefile, not justfile | `make` is installed here; `just` is not. |
| 2026-11-21 | PyJWT rather than python-jose | Smaller and actively maintained; the prompt allowed either. |
| 2026-11-21 | Always-ask list uses the longer list in `docs/09` | Safer superset of `docs/06`; flagged at kickoff. |
| 2026-11-21 | Server-side approval gate moves to phase 3 | The agent loop should never exist without it. |
| 2026-11-21 | `POST /auth/email/start` also takes `code_challenge` | `docs/05` lists `{email}` only, but PKCE needs the challenge at the start. |
| 2026-11-21 | `/auth/callback` returns a small "Open Crew" page, not a bare 302 | A redirect to `crew://` leaves a blank tab and can be blocked without a click. |
| 2026-11-21 | `refresh_tokens.device_id` added | Lets a replayed token revoke one device, and supports "revoke per device" later. |
| 2026-11-21 | Tests use a separate `crew_test` database and Redis db 15 | Tests truncate tables; dev data must be safe. |
| 2026-11-21 | Rust crates pinned to keyring 3, reqwest 0.12, rand 0.8 | Well-known APIs; newer majors changed feature names. |
| 2026-11-21 | `auth_get_tokens` and `api_base_url` commands added | `docs/04` lists the first; the second keeps the API URL in one place (`CREW_API_URL`). |
| 2026-11-24 | WebSocket token goes in the `Sec-WebSocket-Protocol` header, not `?token=` | Query strings land in access logs; flagged at kickoff. Still checked on connect. |
| 2026-11-24 | Each `message.delta` carries its character `offset` | Lets a reconnecting client detect missed text and refetch instead of showing gaps. |
| 2026-11-24 | The bot message row is created when streaming starts and saved about once a second | A refetch mid-stream then shows the partial reply. |
| 2026-11-24 | One reply at a time per chat (`409 bot_busy`) | Two runs in one chat would interleave. |
| 2026-11-24 | `messages.bot_id` and `messages.run_id` use `ON DELETE SET NULL` | The spec left them without a delete rule, which would block deleting a Bot. |
| 2026-11-24 | `.env.example` defaults: `CREW_MODEL=claude-opus-5-5`, `CREW_SMALL_MODEL=claude-haiku-5-5` | Current models; change `CREW_MODEL` to trade cost for capability. |
| 2026-11-24 | `LLM_PROVIDER=fake` dev mode | Lets the app and UI be tried and tested without spending tokens. |
