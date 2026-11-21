# Crew dev commands. Run from the repo root.
COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: up down migrate api worker desktop check check-services check-desktop check-rust

up: ## Start Postgres, Redis and MinIO
	$(COMPOSE) up -d --wait

down: ## Stop them (data volumes are kept)
	$(COMPOSE) down

migrate: ## Apply database migrations
	cd services && uv run alembic upgrade head

api: ## Run the API on http://localhost:8000
	cd services && uv run uvicorn api.main:app --reload --port 8000

worker: ## Run the ARQ worker
	cd services && uv run arq worker.main.WorkerSettings

desktop: ## Open the Crew desktop app in dev mode
	cd apps/desktop && pnpm install && pnpm tauri dev

check: check-services check-desktop check-rust ## Run every linter and test

check-services:
	cd services && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -q

check-desktop:
	cd apps/desktop && pnpm lint && pnpm typecheck && pnpm test

# generate_context! needs the frontend build folder to exist.
check-rust:
	cd apps/desktop && pnpm build
	cd apps/desktop/src-tauri && cargo clippy --all-targets -- -D warnings && cargo test
