# Phase 6: Memory, skills and Primary Bot routing

Build phase 6 only. Read `docs/06-agent-loop.md` (Memory, Primary Bot routing) and `docs/10-ui-spec.md` (Memory and Skills tabs).

## Build

1. Migrations: `memories`, `skills`.
2. Tools: `memory_add(text)`, `memory_remove(id)`. Add memory lines to the system prompt. When memory passes about 2k tokens, a background job asks the LLM to merge similar lines (keep the user's wording).
3. Memory API (list, edit, delete) per Bot.
4. Skills API. Tool `skill_save(name, description, steps, rules)` that creates a skill draft card (needs the user to click Save, not an approval row).
5. Composer `/slug`: the message is sent with `skill_id`; the loop adds the skill's full steps to the prompt for that run.
6. Primary Bot: `handoff(bot_id, task)` tool and other Bots' names + jobs in its prompt. Handoff posts the task in the target Bot's chat and starts a run there; the Primary Bot replies with a link.
7. Tests: memory appears in a new chat's prompt; deleted memory does not; skill run includes steps; handoff creates a run for the right Bot.

## Desktop

1. Memory tab: list, inline edit, delete, "Add line".
2. Skills tab: list, create, edit (markdown editor), delete, Run now.
3. `/` picker in the composer with search.
4. Skill draft card (Save / Cancel).
5. Handoff message style ("Passed to Research Bot", click to open that chat).

## Done means

- Tell a Bot "I prefer short bullet summaries", start a new chat later: it follows that. You can see and delete that line.
- After a task, "save that as a skill" gives a draft card; Save; `/` shows it; running it repeats the task.
- Asking the Primary Bot for research hands it to Research Bot.
- All checks pass.

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
