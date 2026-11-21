# Phase 8: Connectors and Vault

Build phase 8 only. Read `docs/09-security.md` (Vault crypto, secrets), `docs/05-backend-api.md` (Connectors and Vault) and `docs/06-agent-loop.md` (tools).

## Vault

1. Migration: `vault_items`.
2. `crew/vault/crypto.py`: per-item AES-256-GCM with a random data key, wrapped by AWS KMS when `VAULT_KMS_KEY_ID` is set, else by `VAULT_MASTER_KEY` (dev).
3. API: list (names and types only), add, delete. Values are never returned.
4. `crew/vault/inject.py`: replace `{{vault:name}}` in tool args right before execution, inside the tool proxy only. Redact any secret value found in tool results and logs.
5. Tests: round trip, wrong user cannot decrypt, placeholder injection, redaction, a full run where the secret never appears in the LLM request (capture FakeLLM inputs) or logs.

## Connectors

1. Migration: `connectors`.
2. Composio integration for Gmail, Google Calendar, Slack and Notion: connect (OAuth URL opened in the system browser), status, disconnect. Tokens live with Composio or in the Vault, never in plain columns.
3. Real tools: `email_search`, `email_read`, `email_send` (risky), `calendar_list`, `calendar_create` (risky), `slack_read`, `slack_post` (risky), `notion_search`, `notion_update` (risky). Replace the phase 5 fakes.
4. Custom MCP servers: add by URL (+ optional headers stored in the Vault). Use the `mcp` Python client to list tools and call them. Every MCP tool defaults to risky unless the user marks it safe in settings.
5. Per-Bot app access (Apps tab checkboxes): a Bot only gets tools from apps it is allowed.
6. Connector event triggers for routines (new email, new Slack message) via Composio triggers or polling.
7. Tool order the agent should prefer (put in the system prompt): connector first, then API or CLI, then the cloud browser.

## Desktop

1. Settings > Vault: add login, API key, card, note; masked inputs; values never shown again.
2. Settings > Connectors: connect/disconnect, add custom MCP URL, list its tools with a safe/risky toggle.
3. Bot > Apps tab checkboxes.

## Done means

- Connect Gmail; "summarise my last 5 unread emails" works; "reply to the first one" asks for approval.
- Add a GitHub token as `{{vault:github_token}}`; a Bot uses it with `terminal_run` (gh CLI) and the token never shows in chat, logs or the LLM request.
- A custom MCP server's tool is usable by a Bot that has it enabled, and not by one that doesn't.
- All checks pass.

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
