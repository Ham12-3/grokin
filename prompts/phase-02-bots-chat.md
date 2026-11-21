# Phase 2: Bots and streaming chat

Build phase 2 only. Read `docs/05-backend-api.md`, `docs/06-agent-loop.md` (system prompt shape only, no tools yet), `docs/08-data-model.md` and `docs/10-ui-spec.md`.

## Backend

1. Migrations: `bots`, `chats`, `chat_members`, `messages`, `runs`, `usage_daily`.
2. Bot CRUD + Primary Bot (only one per user; first Bot becomes Primary). Limit 50 Bots.
3. Chats: creating a Bot also creates its direct chat. `GET /chats`, messages pagination.
4. `POST /chats/{id}/messages`: save the user message, create a run (`queued`), enqueue an ARQ job, return `{message, run_id}`.
5. Worker job `run_agent(run_id)`: build the system prompt from the Bot, call Claude with streaming (model from `CREW_MODEL`), publish `message.delta` to Redis `chat:{id}`, save the final message, set run `completed`, record token usage in `runs` and `usage_daily`.
6. WebSocket `/ws?token=`: auth on connect, subscribe/unsubscribe with ownership checks, forward Redis events, ping/pong.
7. Tests: cross-user access for bots/chats/messages, WS rejects bad tokens and other users' chats, worker with FakeLLM streams deltas and saves the message.

## Desktop

1. Layout from `docs/10-ui-spec.md`: sidebar (Bots list with Primary star, + menu), chat area, collapsible details pane (empty tabs for now).
2. New Bot dialog: name, avatar (emoji picker), job, instructions, approval mode (saved, used later).
3. Bot settings tab: edit everything, delete with confirm.
4. Chat: message list with infinite scroll up, streaming bot message, composer (Enter to send, Shift+Enter new line), markdown rendering with sanitizing.
5. `src/lib/ws.ts`: single WebSocket, reconnect with backoff, refetch the open chat on reconnect, Zustand store for live deltas.
6. Status dot per Bot (idle / working) from `run.status` events.

## Done means

- Create 2 Bots, chat with each, answers stream smoothly.
- Kill the API for 10 seconds while idle: banner shows "Reconnecting...", it recovers, no lost messages.
- Restart the app: chats and messages are there.
- Token usage appears in `/me`.
- All checks pass.

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
