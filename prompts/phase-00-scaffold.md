# Phase 0: Scaffold the monorepo

Build phase 0 only. Read `CLAUDE.md`, `docs/02-architecture.md` and `docs/03-tech-stack.md` first.

## Build

1. The folder tree from `docs/02-architecture.md` (empty modules are fine, each with a short docstring or README line).
2. `infra/docker-compose.yml` from `templates/docker-compose.yml`: Postgres 16 with pgvector, Redis 7, MinIO.
3. `services/pyproject.toml` with uv: fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, redis, arq, anthropic, httpx, structlog, cryptography, python-jose or pyjwt, pytest, pytest-asyncio, ruff, mypy.
4. `services/shared/crew/config.py` using pydantic-settings, reading `.env` (copy `templates/.env.example` to `.env.example` at the repo root).
5. `services/api/main.py` with `GET /health` returning `{status, version, db, redis}` (real checks).
6. Alembic set up with an empty first migration that enables `vector` and `citext`.
7. `apps/desktop`: `pnpm create tauri-app` style project with React + TypeScript + Vite, Tailwind, shadcn/ui initialised, ESLint + Prettier. Window title "Crew", min size 1000x680.
8. `src-tauri/capabilities/default.json` from `templates/tauri-capabilities-default.json` (only include permissions for plugins installed so far).
9. Root `Makefile` or `justfile` with: `up`, `api`, `worker`, `desktop`, `check`.
10. `.github/workflows/ci.yml`: Python (ruff, mypy, pytest with Postgres + Redis services), desktop (pnpm lint, typecheck, test), Rust (clippy, test). Linux runner is fine for CI.
11. `docs/PROGRESS.md` with sections: Done, Next, Shortcuts taken, Known issues.
12. `.gitignore` covering `.env`, `target/`, `node_modules/`, `.venv/`, `dist/`.

## Done means

- `make up` starts Postgres, Redis, MinIO.
- `make api` then `curl localhost:8000/api/v1/health` shows db and redis ok.
- `make desktop` opens an empty Crew window.
- `make check` passes.

Show me the commands to verify, update PROGRESS.md, suggest a commit message, then stop.
