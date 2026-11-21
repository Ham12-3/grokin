# 01. Product brief

## One line

Crew is a desktop app where you create AI teammates (Bots) that work on their own cloud computer, use your apps, follow routines and ask before doing anything risky.

## Who it is for

- Founders and solo builders who want repeat work done for them (inbox triage, research, reports, posting drafts)
- Project managers and small teams who want status updates, chasing and summaries done every day
- Power users who want an assistant that keeps working when the laptop is closed

## Core ideas

| Idea | What it means for the user |
|---|---|
| Bots | Named teammates. Each has an avatar, one narrow job, its own chat, memory and skills. |
| Primary Bot | One Bot is the default. It answers first and can hand work to the right specialist Bot. |
| Cloud computer | Each user gets one persistent Linux machine. All their Bots share it. It has a browser that stays signed in, a terminal and a filesystem. Each Bot gets its own screen on it. |
| Live screen | The user can watch a Bot use the browser and take over (for logins, CAPTCHAs, passkeys). |
| Approvals | Bots draft risky actions and wait. The user approves, edits or rejects from an approval card. |
| Skills | Saved procedures (name, steps, rules). Made from chat ("save what you just did as a skill"). Run by typing `/` in the composer. |
| Routines | A skill run on a schedule (cron) or on an event (webhook, new email, Slack message). Keep running when the user's devices are off. |
| Connectors | The user's apps (Gmail, Calendar, Drive, Slack, Notion, GitHub) through MCP and OAuth. Custom MCP server URLs too. If no connector fits, the Bot uses the browser. |
| Vault | Encrypted logins, API keys and cards. Bots never see raw values. |
| Memory | Per Bot. Short, readable, editable by the user. |
| Group chats | 2 to 6 Bots plus the user in one chat. Address a Bot with `@`. |
| Library | Every file, page and result Bots made, with search and preview. |

## MVP scope (build these)

1. Desktop app (Windows, macOS, Linux) with login, tray, notifications, auto-update
2. Bots: create, edit, delete, avatar, instructions, Primary Bot
3. Streaming chat with each Bot
4. Agent loop with tools: web search, web fetch, files, browser, terminal
5. Cloud computer per user with live screen view and take over
6. Approvals with three modes per Bot: always ask, ask for risky actions (default), never ask (risky actions still always ask)
7. Memory per Bot (view, edit, delete lines)
8. Skills (create from chat, run with `/`)
9. Routines (cron + webhook), last 20 runs per routine with logs
10. Connectors: Gmail, Google Calendar, Slack, Notion, custom MCP URL
11. Vault
12. Group chats (2 to 6 Bots)
13. Library
14. Usage limits and a daily token budget per user

## Out of scope for the MVP (plan for later, do not build)

Mobile app, phone calls, video generation, team or enterprise sharing, Bot marketplace, billing and payments, local LLMs, voice mode.

## Limits

| Thing | Limit |
|---|---|
| Bots per user | 50 |
| Routines per Bot | 50 |
| Runs kept per routine | 20 |
| Routine runs per hour per user | 300 |
| Group chat size | 2 to 6 Bots |
| Agent loop steps per run | 40 (configurable) |
| Daily token budget per user | configurable, default 2,000,000 |

## Success for v1

- A new user installs the app, signs in and has a working Bot in under 3 minutes.
- A Bot can sign into a website in the cloud browser (with the user taking over for the password), do a task, and the user can watch it live.
- A routine runs every morning at 8am with the laptop off and the result is in the Library.
- No risky action ever runs without an approval row in the database.
