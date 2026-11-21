# Crew

A desktop app where you create AI teammates (Bots) that work on their own cloud computer.
Tauri 2 desktop app plus a Python backend. The full spec is in `docs/`; build status is in
`docs/PROGRESS.md`.

## Run it locally

You need Docker Desktop (running), Rust, Node 20+, pnpm, uv and make.

```
cp .env.example .env      # then fill in what you need
make up                   # Postgres, Redis, MinIO
make migrate              # database migrations
make api                  # API on http://localhost:8000
make worker               # background worker
make desktop              # the desktop app
make check                # all linters and tests
```

Health check: `curl localhost:8000/api/v1/health`
