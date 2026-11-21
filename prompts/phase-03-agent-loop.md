# Phase 3: Agent loop and first tools

Build phase 3 only. Read `docs/06-agent-loop.md` fully and `docs/09-security.md`.

## Build

1. Migration: `tool_calls`.
2. `crew/agent/loop.py` exactly as described: step limit, budget checks, cancel/pause checks, tool calls recorded before and after, untrusted wrapping, finish message.
3. `crew/tools/registry.py`: tool definition (name, JSON schema, risk function, timeout, max output, safe summary), registration, execution with timeouts and output truncation.
4. Tools for this phase: `web_search` (provider from env, behind one function), `web_fetch` (SSRF guard: resolve DNS, block private/link-local/metadata IPs and non-http schemes; extract readable text), `files_write` / `files_read` / `files_list` against a local per-user folder `data/workspaces/{user_id}` for now (the cloud computer comes in phase 4; keep the same interface).
5. Events: `tool.started`, `tool.finished`, `run.status`.
6. `POST /runs/{id}/cancel`. `GET /runs/{id}` and `/runs/{id}/tool-calls`.
7. `FakeLLM` test double and the loop tests listed in `docs/06-agent-loop.md` (approval tests come in phase 5, skip those).

## Desktop

1. Tool step rows in the chat (collapsed, expandable, safe summaries).
2. A "Stop" button while a run is going.
3. A run details drawer: steps, tools, tokens, duration.

## Done means

- "Find the 3 latest Tauri releases and write a summary to notes.md" works: you see search, fetch and write steps, and the file exists.
- Setting `CREW_MAX_STEPS=2` stops a run with a clear message.
- Stop button cancels within 2 seconds.
- `web_fetch http://169.254.169.254` is refused.
- All checks pass, including the FakeLLM loop tests.

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
