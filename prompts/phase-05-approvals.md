# Phase 5: Approvals and notifications

Build phase 5 only. Read `docs/06-agent-loop.md` (approval modes, resume), `docs/09-security.md` (risky actions) and `docs/10-ui-spec.md` (cards).

## Build

1. Migration: `approvals`.
2. `crew/approvals/policy.py`: `check(bot, tool_call) -> Decision(needs_approval, preview)`. Apply the three approval modes. Send, post, publish, buy, pay, delete and share ALWAYS need approval.
3. Loop: on a risky call create the approval, set the run to `waiting_approval`, publish `approval.created`, stop.
4. `POST /approvals/{id}/approve` (optional `edited_args`, validated against the tool schema) re-queues the run with `resume_from_tool_call_id`. `POST /approvals/{id}/reject` adds a tool result "The user rejected this" and re-queues.
5. The worker refuses to execute a risky tool call unless the approval row is `approved` (defence in depth, independent of the loop).
6. Fake connector tools for testing: `email_send(to, subject, body)` and `social_post(text)` that just write to a log table.
7. `browser_submit` risk check: risky on pages with payment, checkout, send or delete forms.
8. Tests: risky call stops the run; approve with edits runs the edited args exactly once; reject continues with the rejection; worker bypass test; `never_ask` still asks for `email_send`.

## Desktop

1. Approval card in chat (preview by type: email, post, purchase, generic JSON), Approve / Edit / Reject.
2. Edit dialog with fields from the preview.
3. Approvals screen (all pending, grouped by Bot) and sidebar badge.
4. Rust `notify` command: when `approval.created` arrives and the window is hidden or unfocused, show a notification; clicking it opens the approval.
5. Tray menu item "Pending approvals (n)".

## Done means

- "Email sam@example.com to say the report is ready" shows an approval card; nothing is sent until you approve.
- Edit the subject, approve: the fake email log shows your edited subject, once.
- Reject: the Bot says it did not send it.
- Hide the window, trigger an approval: you get a desktop notification.
- All checks pass, including the bypass test.

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
