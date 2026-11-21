# PROGRESS

Claude Code updates this file at the end of every phase.

## Current phase

Phase 0 (scaffold): built, waiting for your hands-on check.

## Done

### Phase 0: scaffold

- Repo layout from `docs/02-architecture.md`, placed at the repo root. Modules that belong
  to later phases exist as one-line docstring stubs naming their phase.
- `infra/docker-compose.yml`: Postgres 16 + pgvector, Redis 7, MinIO (from the template).
- `services/`: one uv project (Python 3.12) holding `api`, `worker` and `shared/crew`.
  - `crew/config.py`: pydantic-settings, reads the repo-root `.env`. Secrets hidden in repr.
  - `GET /api/v1/health` returns `{status, version, db, redis}` from real checks with a timeout.
  - Alembic (async) with migration `0001` enabling `vector` and `citext`.
  - ARQ `WorkerSettings` with a placeholder `ping` job.
  - Tests: health (ok, degraded, db unreachable, redis error), config, `.env.example` parses.
- `apps/desktop/`: Tauri 2 + React 18 + TypeScript + Vite, Tailwind 4, shadcn/ui initialised,
  ESLint + Prettier, Vitest. Window "Crew", min size 1000x680. `pnpm gen:api` script wired.
- `src-tauri/capabilities/default.json`: `core:default` and `opener:default` only.
- Root `Makefile`: `up`, `down`, `migrate`, `api`, `worker`, `desktop`, `check`.
- `.github/workflows/ci.yml`: Python, desktop and Rust jobs.
- `.env.example`, `.gitignore`, `README.md`.

## Next

- Phase 1: desktop shell + auth (`prompts/phase-01-desktop-auth.md`).

## Shortcuts taken (to revisit)

- Content Security Policy is still `null` in `tauri.conf.json`. Set the policy from
  `docs/04-desktop-tauri.md` in phase 1, when the API host is wired in.
- shadcn/ui defaults were accepted: neutral colours and the Geist font. `docs/10-ui-spec.md`
  asks for Inter and one accent colour; apply when the first real screens are built.
- `infra/computer/start.sh` is a placeholder and `control_server.py` does not exist, so the
  cloud computer image does not build until phase 4.
- The integration health test skips locally when Postgres or Redis is down. CI sets
  `CREW_REQUIRE_SERVICES=1` so it fails there instead.
- No models or tables yet; each phase adds the tables it needs.

## Known issues

- CI has not run yet: the repo has no GitHub remote and nothing is committed.
- `make` works from Git Bash on this machine; it may not be on the PowerShell PATH.

## Decisions log

| Date | Decision | Why |
|---|---|---|
| 2026-11-21 | Health lives at `/api/v1/health` | `docs/05` sets the base URL; `docs/11` said `/health`. |
| 2026-11-21 | `services/` is one installable uv project (hatchling, `dev-mode-dirs`) | Lets `api`, `worker` and `crew` import each other with the commands in `CLAUDE.md`. |
| 2026-11-21 | React pinned to 18 (template shipped 19) | The stack in `START_PROMPT.md` says React 18. |
| 2026-11-21 | Makefile, not justfile | `make` is installed here; `just` is not. |
| 2026-11-21 | PyJWT rather than python-jose | Smaller and actively maintained; the prompt allowed either. |
| 2026-11-21 | Always-ask list uses the longer list in `docs/09` | Safer superset of `docs/06`; flagged at kickoff. |
| 2026-11-21 | Server-side approval gate moves to phase 3 | The agent loop should never exist without it. |
