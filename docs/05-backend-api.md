# 05. Backend API

Base URL: `/api/v1`. JSON everywhere. Auth: `Authorization: Bearer <access_token>` on every route except `/auth/*` and `/webhooks/*`.

Errors: `{ "error": { "code": "string", "message": "string" } }` with the right HTTP status.

## Auth

| Method | Path | Notes |
|---|---|---|
| GET | `/auth/google/start?redirect=&code_challenge=` | Starts Google OAuth |
| POST | `/auth/email/start` | `{email}`; sends a magic link |
| GET | `/auth/callback` | Finishes login, redirects to `crew://auth?code=` |
| POST | `/auth/exchange` | `{code, code_verifier}` -> `{access_token, refresh_token, user}` |
| POST | `/auth/refresh` | `{refresh_token}` -> new pair (rotate refresh tokens) |
| POST | `/auth/logout` | Revokes the refresh token |
| GET | `/me` | Current user, limits, today's token usage |

## Bots

| Method | Path | Notes |
|---|---|---|
| GET | `/bots` | List |
| POST | `/bots` | `{name, avatar, job, instructions, approval_mode}` |
| GET / PATCH / DELETE | `/bots/{id}` | |
| POST | `/bots/{id}/primary` | Make this the Primary Bot |
| GET | `/bots/{id}/memory` | List memory lines |
| PATCH / DELETE | `/bots/{id}/memory/{line_id}` | User edits memory |

## Chats and messages

| Method | Path | Notes |
|---|---|---|
| GET | `/chats` | Sidebar list (direct + group) |
| POST | `/chats` | `{bot_ids: [..]}`; 1 Bot = direct chat, 2 to 6 = group |
| GET | `/chats/{id}/messages?before=&limit=` | Paginated |
| POST | `/chats/{id}/messages` | `{content, attachments?, mention_bot_id?, skill_id?}` -> `{message, run_id}` |

## Runs

| Method | Path | Notes |
|---|---|---|
| GET | `/runs/{id}` | Status, steps, token usage |
| GET | `/runs/{id}/tool-calls` | Audit trail |
| POST | `/runs/{id}/cancel` | |
| POST | `/runs/{id}/pause` / `/resume` | Used by "Take over" |

## Approvals

| Method | Path | Notes |
|---|---|---|
| GET | `/approvals?status=pending` | |
| POST | `/approvals/{id}/approve` | `{edited_args?}`; re-queues the run |
| POST | `/approvals/{id}/reject` | `{reason?}`; the Bot is told it was rejected |

## Skills

| Method | Path | Notes |
|---|---|---|
| GET / POST | `/bots/{id}/skills` | |
| PATCH / DELETE | `/skills/{id}` | |
| POST | `/chats/{id}/skills/from-chat` | Bot drafts a skill from the last task; user confirms |

## Routines

| Method | Path | Notes |
|---|---|---|
| GET / POST | `/bots/{id}/routines` | `{skill_id, trigger: {type:"cron", cron, timezone} or {type:"webhook"} or {type:"connector_event", connector, event}, notify}` |
| PATCH / DELETE | `/routines/{id}` | |
| POST | `/routines/{id}/pause` / `/resume` / `/test` | |
| GET | `/routines/{id}/runs` | Last 20 |
| POST | `/webhooks/routines/{routine_id}/{secret}` | Public; secret checked in constant time |

## Connectors and Vault

| Method | Path | Notes |
|---|---|---|
| GET | `/connectors` | Available + connected |
| POST | `/connectors/{kind}/connect` | Returns an OAuth URL (opened in the system browser) |
| POST | `/connectors/mcp` | `{name, url, headers_secret_ref?}` custom MCP server |
| DELETE | `/connectors/{id}` | |
| GET | `/vault` | Names and types only, never values |
| POST | `/vault` | `{name, type, value}`; value is encrypted before it is stored |
| DELETE | `/vault/{id}` | |

## Computer

| Method | Path | Notes |
|---|---|---|
| GET | `/computer` | The user's computer: status, provider, created |
| POST | `/computer/start` / `/stop` | |
| WS | `/computer/{id}/vnc?bot_id=` | VNC proxy for the live screen |

## Library

| Method | Path | Notes |
|---|---|---|
| GET | `/library?q=&bot_id=&type=` | Files, pages, results |
| GET | `/library/{id}` | Metadata + signed download URL |

## WebSocket `/ws?token=`

Client to server:

```json
{"type":"subscribe","chat_id":"..."}
{"type":"unsubscribe","chat_id":"..."}
{"type":"ping"}
```

Server to client (every event has `type`, `ts` and ids):

| type | payload |
|---|---|
| `message.created` | full message |
| `message.delta` | `{message_id, text}` streamed tokens |
| `message.completed` | `{message_id}` |
| `run.status` | `{run_id, status}` queued, running, waiting_approval, paused, completed, failed, cancelled |
| `tool.started` | `{run_id, tool_call_id, tool, summary}` (summary is safe text, no secrets) |
| `tool.finished` | `{run_id, tool_call_id, ok, summary}` |
| `approval.created` | full approval card |
| `approval.resolved` | `{approval_id, status}` |
| `routine.completed` | `{routine_id, run_id, ok}` |
| `computer.status` | `{computer_id, status}` |
| `pong` | |

Redis channels: `chat:{chat_id}` and `user:{user_id}`. The API WebSocket handler subscribes to the user channel on connect and to chat channels on `subscribe`, after checking the user owns the chat.
