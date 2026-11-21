# 11. Build phases

Each phase ends with a working app. Each has a prompt in `prompts/`. "Done means" is the checklist you test by hand before moving on.

| # | Phase | Done means |
|---|---|---|
| 0 | Scaffold | `docker compose up` starts Postgres + Redis. `uv run uvicorn` serves `/health`. `pnpm tauri dev` opens an empty window. CI runs lint + tests on push. |
| 1 | Desktop shell + auth | Sign in with email magic link (dev: link printed in the API log) and Google. Refresh token in the OS keychain. Closing the window hides to tray. Tray menu works. Deep link works with the app already open (Windows). Logout clears the keychain. |
| 2 | Bots + streaming chat | Create, edit, delete Bots; set Primary. Send a message, see Claude stream the answer token by token over the WebSocket. Reconnect works after killing the API for 10 seconds. Messages persist. |
| 3 | Agent loop + tools | Bot can web search, fetch a page and write a file. Tool step rows show in the chat. `runs` and `tool_calls` filled. Step and token limits stop a run with a clear message. Cancel works. FakeLLM tests pass. |
| 4 | Cloud computer + live screen | First run starts the user's computer (Docker). Bot opens a website in Chromium and reads it. Live screen panel shows it. Take over + give back works. Files persist after the computer restarts. Idle pause after 10 min. |
| 5 | Approvals + notifications | A Bot drafting an email (use a fake `email_send` tool for now) stops and shows an approval card. Approve with an edit sends the edited version. Reject tells the Bot. Desktop notification when the window is hidden. Approvals screen lists all pending. Bypass test passes. |
| 6 | Memory, skills, Primary Bot | Bot remembers a stated preference in a new chat. User edits and deletes memory lines. "Save that as a skill" creates a skill draft card; `/skill` runs it. Primary Bot hands a research request to Research Bot. |
| 7 | Routines | Create a daily routine; use "Test run". Cron fires with the desktop app closed. Webhook routine fires from `curl`. Last 20 runs kept with logs. Risky actions from routines become drafts and the run is `needs_review`. |
| 8 | Connectors + Vault | Connect Gmail and Slack through Composio OAuth. Add a custom MCP server URL and use one of its tools. Vault items saved encrypted; a tool uses `{{vault:name}}` and the secret never appears in logs or LLM input (test). |
| 9 | Group chats + Library | Create a group with 3 Bots. `@mention` works, unaddressed messages get one sensible responder, Bot-to-Bot turns are capped. Library shows files from `/workspace/outputs` with preview and download. |
| 10 | Release | Signed installers for Windows, macOS, Linux built by CI. Auto-update from v0.1.0 to v0.1.1 works. Crash reporting on. Security checklist in `09-security.md` passes. |
| 11 | Local bridge (optional) | With permission, a Bot reads a file from a folder the user picked on their own computer. Every call asks. Offline app returns "local computer not available". |

## Order of risk

The riskiest parts are the cloud computer (phase 4) and approvals (phase 5). Do not polish UI before these work end to end.

## After every phase

1. All checks pass (see `CLAUDE.md` commands).
2. `docs/PROGRESS.md` updated.
3. You test the "Done means" list by hand.
4. Commit and tag (`phase-3-done`).
