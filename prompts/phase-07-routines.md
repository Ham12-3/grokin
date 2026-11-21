# Phase 7: Routines

Build phase 7 only. Read `docs/05-backend-api.md` (Routines), `docs/06-agent-loop.md` (routine runs never wait at night) and `docs/08-data-model.md` (routines).

## Build

1. Migration: `routines` (+ `routine_id` on runs is already there).
2. Scheduler in the worker (ARQ cron every minute): find routines with `next_run_at <= now()` and not paused, enqueue a run, compute the next time with `croniter` in the routine's timezone. Use a Redis lock so two workers never fire the same routine.
3. Triggers: cron, webhook (`POST /webhooks/routines/{id}/{secret}`, secret hashed, constant-time compare, rate limit), and a stub for connector events (wired in phase 8).
4. Routine runs: risky actions become pending approvals marked `from_routine`, the run ends `needs_review` instead of waiting.
5. Limits: 50 routines per Bot, 300 routine runs per hour per user, keep the last 20 runs per routine (hourly cleanup job).
6. Routine API: CRUD, pause, resume, test run, runs list with logs.
7. `routine.completed` event; notify only if `notify=true`.
8. Tests: next-run maths across DST, lock prevents double fire, webhook secret check, needs_review path, cleanup keeps 20.

## Desktop

1. Routines tab: list (next run, last result), New routine dialog (skill, trigger presets + custom cron with a human-readable preview, webhook shows the URL once, notify toggle).
2. Run history with expandable logs (tool steps).
3. Tray item "Pause all routines".

## Done means

- A routine set for 2 minutes from now fires with the desktop app fully quit, and the result is in its run history.
- `curl -X POST` to the webhook URL fires it; a wrong secret gets 404.
- A routine that drafts an email ends `needs_review` with a pending approval.
- All checks pass.

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
