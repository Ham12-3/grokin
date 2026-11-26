# Crew backend: one image for the API and the worker (different commands).
#   docker build -t crew-services services
#   API:     docker run crew-services
#   Worker:  docker run crew-services arq worker.main.WorkerSettings
#   Migrate: docker run crew-services alembic upgrade head
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --extra aws

COPY . .
RUN uv sync --locked --no-dev --extra aws


FROM python:3.12-slim

# Not root: nothing in here needs it.
RUN useradd --system --uid 10001 --home /app crew
WORKDIR /app
COPY --from=build --chown=crew:crew /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CREW_ENV=prod
USER crew
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
