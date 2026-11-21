# 09. Security

Bots can browse the web, read email and take actions. Treat security as a feature from day one.

## Threats and what we do

| Threat | Defence |
|---|---|
| Prompt injection from web pages, emails, files | Wrap all outside content in `<untrusted>` tags. System prompt says it is data. Risky actions always need approval, so injected instructions cannot send or delete anything alone. Never give tools that read untrusted data AND send data out in the same step without approval. |
| Model leaks secrets | The model never sees secrets. Tools get `{{vault:name}}` placeholders; the tool proxy swaps them in after the model call. Tool results are scanned and any secret value is replaced with `[redacted]` before going back to the model or logs. |
| Model approves its own actions | Approvals are rows in Postgres that only the authenticated user's `POST /approvals/{id}/approve` can change. The worker checks the row status before running a risky tool. |
| One user reaches another user's data | Every query filters by `user_id`. Add a pytest that tries cross-user access on every router. |
| One user reaches another user's computer | Separate container/sandbox and volume per user. VNC and control server only through the API proxy with an ownership check. |
| Stolen desktop session | Refresh token only in the OS keychain. Access tokens last 15 minutes. Refresh tokens rotate and can be revoked per device in settings. |
| SSRF through `web_fetch` | Block private IP ranges, link-local, cloud metadata, and non-HTTP schemes. Resolve DNS and check the IP before connecting. |
| XSS in the desktop app | Sanitize markdown. Strict CSP. No `dangerouslySetInnerHTML`. Minimal Tauri capabilities. |
| Webhook abuse | Random 32-byte secret per routine, constant-time compare, rate limit per routine. |
| Runaway cost | Step limit per run, token budget per run and per day, routine rate limits, auto-pause idle computers. |

## Risky actions (always need approval, whatever the Bot's mode)

Send (email, message, DM), post or publish, buy or pay, delete, share (change permissions or send links outside), submitting a payment or checkout form, changing account settings, creating forwarding rules.

## Vault crypto

- Per item: random 32-byte data key, AES-256-GCM encrypt the value, wrap the data key with AWS KMS (prod) or with `VAULT_MASTER_KEY` via AES key wrap (dev).
- Decrypt only inside the tool proxy, only for the call that needs it, and only in memory.
- Never log decrypted values. Add a log filter that redacts anything matching known secret values for the current run.

## Audit

Write to `audit_log` for: login, logout, bot create/delete, approval approve/reject, vault add/delete/use, connector connect/disconnect, computer start/stop, routine create/pause/delete.

## Checklist before any release

- [ ] Cross-user access tests pass for every router
- [ ] No secret appears in logs during the full test suite (grep test logs for test secret values)
- [ ] Approval cannot be bypassed (test: worker given a risky tool call without an approved row refuses to run it)
- [ ] `web_fetch` blocks 127.0.0.1, 10.0.0.0/8, 169.254.169.254, file://
- [ ] Tauri capabilities list only the needed commands
- [ ] CSP set and no inline scripts
