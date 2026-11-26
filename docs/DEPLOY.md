# Deploying the Crew backend

One image runs both the API and the worker. You also need Postgres 16 with `pgvector`,
Redis, and a place for the per-user cloud computers.

## 1. Build the image

```
docker build -t crew-services services
```

| Process | Command |
|---|---|
| API | (default) `uvicorn api.main:app --host 0.0.0.0 --port 8000` |
| Worker | `arq worker.main.WorkerSettings` |
| Migrations | `alembic upgrade head` (run before the new API version starts) |

Run exactly one worker to begin with. More than one is safe (routines fire once, runs are
claimed once), but Library files must then be on shared storage (see below).

## 2. Settings

Start from `.env.example`. Keep secrets in your platform's secret manager, never in the image.

| Setting | Production value |
|---|---|
| `CREW_ENV` | `prod` (refuses the fake model and the stand-in app service) |
| `API_BASE_URL` | The public https address of the API. Used in sign-in links, webhook and download addresses. |
| `JWT_SECRET` | 64 random characters. Changing it signs everyone out. |
| `DATABASE_URL`, `REDIS_URL` | Your managed Postgres (with `pgvector`) and Redis |
| `ANTHROPIC_API_KEY`, `CREW_MODEL`, `CREW_SMALL_MODEL` | Required for real answers |
| `SMTP_URL`, `EMAIL_FROM` | Required: sign-in links are emailed |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Optional: "Continue with Google" |
| `SEARCH_API_KEY` | Optional: web search |
| `VAULT_KMS_KEY_ID` | An AWS KMS key. Without it (or `VAULT_MASTER_KEY`) the Vault is off. |
| `COMPOSIO_API_KEY` | Optional: Gmail, Calendar, Slack, Notion |
| `LIBRARY_STORAGE`, `S3_*` | `s3` and a bucket, unless a single server with a disk is enough |
| `COMPUTER_PROVIDER` | `docker` needs a Docker socket on the worker's host. See "Cloud computers". |
| `SENTRY_DSN` | Optional: error reports (no message contents) |
| `MIN_DESKTOP_VERSION` | Raise it when an API change breaks older desktop apps |
| `CORS_ORIGINS` | Leave the default: the desktop app's own origins |

## 3. Health checks

- API: `GET /api/v1/health` returns 200 with the state of the database and Redis.
- Worker: the Redis key `worker:heartbeat` is rewritten every minute and expires after 3.
  If it is missing, no worker is running.

## 4. Cloud computers

Each user's computer is a container started by the worker (`COMPUTER_PROVIDER=docker`,
image built with `make computer-image`). The worker therefore needs access to a Docker
daemon, and that host needs enough memory (up to `COMPUTER_MEMORY` per active user). This
suits one virtual machine well. A container platform that gives no Docker access (Fly
Machines, ECS Fargate) cannot run them: there, run the worker on a VM, or finish the E2B
provider (`crew/computer/e2b_provider.py`, a stub today).

## Fly.io (API only) plus one VM (worker and computers)

1. `fly launch --no-deploy` in `services/`, then in `fly.toml`:
   - `[deploy] release_command = "alembic upgrade head"`
   - `[http_service] internal_port = 8000`, with a check on `/api/v1/health`
2. `fly postgres create` (enable `pgvector`: `CREATE EXTENSION vector;`) and a Redis
   (Upstash from `fly redis create`).
3. `fly secrets set JWT_SECRET=... ANTHROPIC_API_KEY=... DATABASE_URL=... REDIS_URL=...`
4. `fly deploy`
5. On a VM with Docker: build `crew-computer` and run the same image with
   `arq worker.main.WorkerSettings`, the same settings, and `/var/run/docker.sock` mounted.
   It must reach the same Postgres and Redis.

## AWS

- API: ECS service (Fargate is fine) behind an ALB, health check `/api/v1/health`.
- Migrations: a one-off ECS task running `alembic upgrade head` before each deploy.
- Worker and computers: an ECS service on EC2 capacity (or a plain EC2 instance) with the
  Docker socket mounted.
- RDS Postgres 16 (`CREATE EXTENSION vector;`), ElastiCache Redis, S3 for the Library, KMS
  for the Vault, Secrets Manager for the secrets.

## What has and has not been tried

The image was built and started in production mode against Postgres and Redis: migrations
ran and `/api/v1/health` answered. Nothing has been deployed to Fly.io or AWS: expect to
adjust the platform-specific steps. Note that in production the API refuses to start
without `SMTP_URL`, because sign-in links must never be written to a log.
