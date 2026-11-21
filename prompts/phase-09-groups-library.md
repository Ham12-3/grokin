# Phase 9: Group chats and Library

Build phase 9 only. Read `docs/06-agent-loop.md` (Group chats) and `docs/10-ui-spec.md` (Library).

## Group chats

1. `POST /chats` with 2 to 6 Bot ids creates a group.
2. Mentions: `@name` in the message routes to those Bots in order.
3. No mention: a cheap responder-picker call chooses one Bot or none.
4. Bots can `@mention` each other; cap at 6 Bot turns per user message.
5. Approvals and Vault requests are never shown in a group; the Bot posts a pointer and the card goes to its direct chat.
6. Tests: mention routing, cap, approvals redirected.

## Library

1. Migration: `library_items`.
2. Tool `library_add(path, title)`; also auto-register new files in `/workspace/outputs` at the end of a run.
3. Copy files to object storage (MinIO in dev, S3 in prod) for download; signed URLs that expire.
4. API: list with search and filters, item details.
5. Desktop: Library screen (grid/list, search, filters by Bot and type), preview panel (markdown, images, PDF, text), Save to computer (Tauri save dialog via `tauri-plugin-dialog`; add it to capabilities with save-only permission).
6. File cards in chat link to the Library item.

## Done means

- A group of 3 Bots: `@Research` answers alone; an unaddressed question gets one sensible answer; Bots talking to each other stop after 6 turns.
- A report the Bot wrote shows in the Library, previews, and saves to your computer.
- All checks pass.

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
