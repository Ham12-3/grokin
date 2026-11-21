# 10. UI spec

Original Crew design. Do not copy Grok or xAI styling. Clean, calm, dark and light themes, one accent colour (pick one, for example indigo), Inter font, 8px spacing grid.

## Main window layout

```
+------------------+--------------------------------------+--------------------+
| SIDEBAR (260px)  | CHAT                                 | DETAILS / SCREEN   |
|                  |                                      | (360px, toggle)    |
| [+] New          |  Bot name  status dot   [screen][i]  |                    |
| Search           |--------------------------------------|  Tabs:             |
|                  |  messages, cards, tool steps         |  - Screen          |
| BOTS             |                                      |  - Memory          |
|  * Primary Bot   |                                      |  - Skills          |
|  Inbox Bot       |                                      |  - Routines        |
|  Research Bot    |                                      |  - Apps            |
| GROUPS           |                                      |  - Settings        |
|  Launch team     |--------------------------------------|                    |
| Approvals (3)    |  [ / skills  @ bots  attach ] [send] |                    |
| Library          |                                      |                    |
| Settings         |                                      |                    |
+------------------+--------------------------------------+--------------------+
```

## Sidebar

- `+` menu: New chat, New Bot, New group chat.
- Bot rows: avatar, name, a small status dot (idle, working, waiting for you). A star marks the Primary Bot.
- Approvals row with a count badge.
- Library, Settings at the bottom.

## Chat

- Messages: user on the right, Bot on the left with avatar.
- Streaming text with a soft cursor.
- **Tool step rows** (collapsed by default): "Searched the web for ...", "Opened linkedin.com", "Wrote report.md". Expand to see details. Never show secrets.
- **Cards** inside the chat:
  - Approval card: title, preview (email: to, subject, body; post: text; purchase: item and total), buttons Approve, Edit, Reject.
  - Takeover card: "Needs you to sign in to X", button Open screen.
  - File card: name, size, Open, Save to computer.
  - Page card: title + preview of a report or web page the Bot made.
  - Skill draft card: name, steps, Save skill / Cancel.
- Composer: multi-line, `/` opens the skills picker, `@` opens the Bot picker (group chats), paperclip to attach files (uploaded to `/workspace/inbox`). Enter sends, Shift+Enter new line.

## Details pane tabs

- **Screen**: live noVNC view of the Bot's display. Buttons: Take over / Give back, Fullscreen.
- **Memory**: list of lines, edit inline, delete.
- **Skills**: list, New skill, edit steps (markdown), run now.
- **Routines**: list with next run time, last result, toggles. New routine: pick skill, pick trigger (every day at, every weekday at, every hour, custom cron, webhook, connector event), notify on/off. Last 20 runs with logs.
- **Apps**: connectors this Bot may use (checkboxes).
- **Settings**: name, avatar, job, instructions, approval mode (Always ask, Ask for risky actions, Never ask), delete Bot.

## Other screens

- **Onboarding** (first launch): sign in, create your first Bot from 4 templates (Inbox helper, Researcher, Social drafter, Daily reporter) or blank, connect one app (optional).
- **Approvals**: all pending approvals across Bots, grouped by Bot, with the same cards.
- **Library**: grid and list views, search, filter by Bot and type, preview panel.
- **Settings (app)**: account, devices (revoke), Vault (add login, API key, card, note; values masked, never shown again after saving), Connectors (connect, disconnect, add custom MCP URL), Computer (status, start, stop, restart), Usage (today's tokens vs budget), Notifications, Theme, Start at login, Updates.

## States to design

Empty states for every list, loading skeletons, offline banner ("Reconnecting..."), computer starting ("Starting your computer, about 20 seconds"), budget reached, errors with a Retry button.

## Keyboard shortcuts

Ctrl/Cmd+K quick switcher, Ctrl/Cmd+N new chat, Ctrl/Cmd+Shift+A approvals, Ctrl/Cmd+\ toggle details pane, Esc closes dialogs. Global: Ctrl/Cmd+Shift+Space opens Crew.
