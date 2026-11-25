# PROGRESS

Claude Code updates this file at the end of every phase.

## Current phase

Phase 5 (approvals + notifications): built and verified on Linux. Waiting for your hands-on
check in the desktop app on Windows (with phase 4) before phase 6 starts.

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

### Phase 3: agent loop + first tools

Backend

- Migration `0004`: `tool_calls` (with `user_id`, `step`, `llm_tool_use_id`, `summary`) and
  `runs.transcript`.
- `crew/agent/loop.py`: calls the LLM, runs the tools it asks for, repeats. Step limit
  (`CREW_MAX_STEPS`), per-run token limit (`CREW_MAX_RUN_TOKENS`), daily budget, cancel.
  Every tool call is written before it runs and updated after. The run's assistant turns and
  tool results are saved in `runs.transcript`.
- `crew/tools/registry.py`: tool definition (JSON schema, risk function, timeout, max output,
  safe summary), argument validation, timeouts, truncation, `<untrusted>` wrapping that
  cannot be closed from inside.
- `crew/approvals/policy.py`: the server-side gate. A risky call, or any write by an
  `always_ask` Bot, is NOT run; the model is told it needs approval. Cards arrive in phase 5.
- Tools: `web_search` (Brave behind one function), `web_fetch` (SSRF guard in
  `crew/tools/net.py`), `files_write` / `files_read` / `files_list` on a per-user folder
  `data/workspaces/{user_id}` behind a `Workspace` interface.
- Events `tool.started`, `tool.finished`; `run.status` gains `cancelled`.
- `GET /runs/{id}`, `GET /runs/{id}/tool-calls`, `POST /runs/{id}/cancel`. Message pages
  include the tool steps of their runs.
- `FakeLLM` plays scripted turns with tool calls. With `LLM_PROVIDER=fake`, a message that
  contains a link makes it fetch the page and save `notes.md`.

Desktop

- Tool step rows inside the reply: collapsed, expandable, safe summaries only.
- Stop button while a run is going.
- "Details" under each reply: status, steps, tools, tokens, duration.

### Phase 4: cloud computer + live screen

The computer

- `infra/computer`: Ubuntu image with Xvfb, Fluxbox, x11vnc, Playwright's Chromium and a
  control server (`control_server.py`) on port 7000, protected by a per-computer token.
  Build it with `make computer-image`.
- `start.sh` blocks private networks and the cloud metadata address with iptables (DNS to
  Docker's resolver is allowed), then drops to the unprivileged `crew` user for good.
- Screens start on demand, one per display (1 to 6): Xvfb, window manager, VNC, Chromium
  with a persistent profile.
- Only the control port is published, and only on 127.0.0.1. Commands, files, the browser
  (Playwright over CDP, inside the machine) and the live screen all go through the control
  server.

Backend

- Migration `0005`: `computers`.
- `ComputerProvider` with `DockerProvider` (one container per user, named volumes for
  `/workspace` and the browser profile, CPU / memory / process limits, capabilities dropped),
  `LocalProvider` (files only: used by tests and by servers without Docker) and an
  `E2BProvider` stub with TODOs.
- Screen allocation in Redis per user; released when the run ends.
- File tools now run on the computer. New tools: `terminal_run`, `browser_open`,
  `browser_read`, `browser_click`, `browser_type`, `browser_screenshot`, `request_takeover`.
  Risky terminal commands and clicks on send / pay / delete style buttons are refused by the
  approval gate.
- `GET /computer`, `POST /computer/start|stop`, `computer.status` events, idle auto-pause
  every minute (`COMPUTER_IDLE_MINUTES`).
- `WS /computer/{id}/vnc?bot_id=`: token in the subprotocol, owner-only, piped to the Bot's
  screen.
- `POST /runs/{id}/pause` and `/resume`; a paused run sends heartbeats and can be cancelled.

Desktop

- Screen tab: computer status, Start / Stop / Restart, the live noVNC view (watch-only by
  default), Take over / Give back.
- Takeover card in the chat with Open screen and Give back.
- "Starting your computer..." notice in the chat.
- Settings tab: "Your computer" with its status and Start / Stop / Restart.

Dev mode (`LLM_PROVIDER=fake`)

- The scripted model can now show phase 4 without an API key: `browse <link>` opens the page
  on the computer and takes a screenshot; `sign in <link>` opens it and asks you to take over.

Verified on 2026-11-25 (Linux, Docker 29, real containers)

- `make check-slow`: 9 of 9 pass. The container starts, commands run as `crew`, files stay
  inside `/workspace`, private networks and the metadata address are blocked, the public
  internet works, a wrong token is refused, the browser opens and clicks, the screen speaks
  VNC, and files plus the browser profile survive a restart.
- API + worker + Docker computer, driven over HTTP: the first browser message started the
  computer and finished in about 5 seconds; the owner's screen connected; another signed-in
  user and a bad token were both refused (403); a `sign in` request paused on
  `request_takeover` and finished after Give back; Stop then Start worked.
- The real frontend in a browser (Rust core stubbed): the Screen tab showed the live screen,
  and after Take over the keyboard and mouse reached the remote browser.
- Not verified here: the packaged Tauri window on Windows, a real GitHub sign-in surviving a
  restart (a marker file in the browser profile did), and real Claude driving the browser.
- The container exit seen earlier on the Windows machine did not happen here. If it does
  again, `docker logs crew-computer-<user id>` shows why (`start.sh` prints its reason).

### Phase 5: approvals + notifications

Backend

- Migration `0006`: `approvals`, `connector_log` (what the test connectors "sent") and
  `runs.pending_results`.
- A call that needs approval creates an `approvals` row, the run stops as
  `waiting_approval` and `approval.created` is published. Nothing runs.
- `GET /approvals?status=`, `POST /approvals/{id}/approve` (optional `edited_args`, checked
  against the tool's schema) and `POST /approvals/{id}/reject`. Both queue the run again;
  the loop continues from the database: tools that already ran in that step are not
  repeated, and the same reply message continues.
- `crew/approvals/gate.py`: every tool execution in the worker goes through it. A risky call
  runs only with an `approved` row of the same user, and that row works once.
- Reject tells the Bot the user said no. Stop while waiting cancels the run and expires the
  approval. A chat stays busy while its Bot waits for an answer.
- Test connectors `email_send` and `social_post` (always risky; they only write to
  `connector_log`). `browser_submit` is risky on payment, checkout, send and delete pages.
- Approve and reject are written to `audit_log`.

Desktop

- Approval card in the chat (email, post, purchase, or the raw details), with Approve,
  Edit and Reject. Edit opens a form (or JSON for other tools) and approves the changed
  version.
- Approvals screen (all pending, grouped by Bot), sidebar row with a count, amber
  "Waiting for you" dot, Ctrl/Cmd+Shift+A.
- Rust `notify` and `set_tray_badge` commands; tray item "Pending approvals (n)" and the
  count in the tray tooltip. A notification is shown only when the window is hidden or
  not in front.

Dev mode (`LLM_PROVIDER=fake`): a message with `email` and an address drafts an email for
approval.

Verified on 2026-11-25 (Linux)

- Backend: 215 tests pass, including the worker bypass test (pending, rejected, expired,
  missing and another user's approval are all refused) and the 9 real-container tests.
- API + worker + the real frontend in a browser (Rust core stubbed): an email request showed
  the card; Edit changed the subject; after approving, `connector_log` held the edited
  subject exactly once. A second email rejected from the Approvals screen was not sent and
  the Bot said so. The notify and tray-badge calls were made with the right text and counts.
- Not verified here: the real desktop notification and tray on Windows (the Rust code
  compiles and its logic is unit-tested, but it has only run on Linux without a display),
  and real Claude going through an approval.

## Next

- Phase 6: memory + skills (`prompts/phase-06-memory-skills.md`).

## Shortcuts taken (to revisit)

- Clicking a notification does not open the approval by itself: Tauri's notification plugin
  has no click event on desktop. Instead, after a notification the Approvals screen opens
  the next time the Crew window comes to the front, and the tray has "Pending approvals".
- Approvals never expire on their own; a waiting run keeps its chat busy until you answer
  or press Stop.
- Approval cards are not stored as chat messages (`messages.card`): the chat shows pending
  ones from the approvals list, and the step row shows how each ended.
- `resume_from_tool_call_id` is not passed to the worker: the loop finds the waiting call
  in the database, which is the same information and cannot disagree with it.
- A browser click approved after a wait runs against the page as it is then; if the page
  changed, the element number may no longer match and the click fails with a clear error.
- `browser_submit` was not run against a real page in a container (unit and fake-provider
  tests only).

- Browser logins are kept per screen, not shared between the six screens: Chromium cannot
  share one profile between running copies. A Bot working alone always gets screen 1, so its
  logins persist; a second Bot working at the same time has its own.
- `browser_screenshot` saves a PNG to `/workspace/outputs/screenshots`; the Bot cannot look
  at the picture itself yet.
- Take over is enforced in the app only: the screen is watch-only until you press Take over,
  but the server does not filter input.
- Take over pauses the Bot before its next step or tool, not in the middle of a reply.
- The computer image has no `ffmpeg` (the spec lists it); add it when a task needs it.
- Computer status and Start / Stop live in the Screen tab; there is no app-wide Settings
  screen yet.
- `E2BProvider` is a stub. `/workspace` uploads from the composer (attach) are not built.
- The idle auto-pause was tested with a fake computer, not timed against a real container.

- Real Claude was verified on 2026-11-25 with `services/scripts/smoke_live.py` (a plain
  reply and a fetch-then-write tool loop on `claude-opus-5-5`). The desktop app itself has
  not been driven against real Claude yet, only against `FakeLLM`.
- `web_search` has not run against the real Brave API (no `SEARCH_API_KEY`); it is tested
  with a stubbed response. Without a key the tool tells the model to use `web_fetch`.
- Raw tool arguments are stored in `tool_calls.args` but not returned by the API yet.
- Earlier runs' tool results are not replayed to the model in later turns; it sees the
  earlier replies as text only.
- Server-side refusal fallbacks (the Anthropic `fallbacks` beta) are not enabled; a refused
  request shows a short "can't help with that" reply. Decide when a key is available.
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
- The integration tests skip locally when Postgres or Redis is down. CI sets
  `CREW_REQUIRE_SERVICES=1` so they fail there instead.

## Known issues

- A failed step still reads "Opened example.com" (with a warning icon and the reason
  when expanded): step summaries are written before the tool runs.
- The first tool that needs the computer waits for it to start (about 10 to 40 seconds).
- With `COMPUTER_PROVIDER=docker`, every user's container runs on this machine and asks
  for up to 3 GB of memory. Fine for development, not for many users.

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
| 2026-11-24 | Messages and tools use Anthropic's own shapes inside the LLM interface | The transcript can be stored and replayed exactly, including blocks the app does not read. |
| 2026-11-24 | `web_fetch` connects to the IP address it checked, with the original Host and TLS name | A second DNS answer cannot redirect the request to an internal address. |
| 2026-11-24 | Step and token limits end the run as `completed` with a note in the reply and a code in `runs.error` | The work done so far is kept and the user sees why it stopped. |
| 2026-11-24 | Stop interrupts the run's task, and the final write uses a fresh database session | It works mid-stream and mid-tool, within about a second. |
| 2026-11-24 | `tool_calls.user_id` added | Every per-user table is filtered by `user_id` directly. |
| 2026-11-24 | `jsonschema` validates tool arguments | The model's arguments are checked before any tool code runs. |
| 2026-11-25 | `services/scripts/smoke_live.py` added | A manual check against the real Anthropic API, as `docs/12` asks. Never run in CI. |
| 2026-11-25 | The backend drives the browser through the control server, not a published CDP port | Chromium's debugging port never leaves the machine; one token-protected door instead of several ports. |
| 2026-11-25 | The control server bridges VNC itself (no websockify) | Same reason: one port, one token. |
| 2026-11-25 | Each computer's token is derived (HMAC of the user id), only its hash is stored | Nothing secret to keep in the database or to lose on restart. |
| 2026-11-25 | Network lockdown inside the container with iptables, then privileges dropped | A Bot, or a page steering it, cannot reach the host, the database or cloud metadata. |
| 2026-11-25 | `COMPUTER_PROVIDER=local` added | Tests and Docker-less servers still get file tools. |
| 2026-11-25 | Tool risk functions receive the tool context | A click's risk depends on the label of the element the Bot last read. |
| 2026-11-25 | A run counts as alive by `updated_at` heartbeats, and `paused` counts as active | A long Take over must not look like a dead run. |
| 2026-11-25 | Chromium starts with `--hide-crash-restore-bubble` | Stopping the computer kills the browser; the "Restore pages?" bubble covered the page afterwards. |
| 2026-11-25 | Computer controls appear in Settings as well as the Screen tab | `prompts/phase-04` asks for Settings; the Screen tab is where you need them while watching. |
| 2026-11-25 | The approval check lives in one gate that every tool execution passes | The worker refuses a risky call without an approved row even if the loop is wrong. |
| 2026-11-25 | An approved row is claimed in one UPDATE and works once | A re-queued or repeated job cannot send the same email twice. |
| 2026-11-25 | Risky calls in one step are asked one at a time | Each card is answered knowing what already happened. |
| 2026-11-25 | `approvals` has extra columns: `chat_id`, `tool`, `reason`, `executed_at` | Cards need the chat and tool without joins; `executed_at` is the once-only mark. |
