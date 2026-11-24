# Crew

A desktop app where you create AI teammates (Bots) that work on their own cloud computer.
Tauri 2 desktop app plus a Python backend. The full spec is in `docs/`; build status is in
`docs/PROGRESS.md`.

## Run it locally

You need Docker Desktop (running), Rust, Node 20+, pnpm, uv and make.

```
cp .env.example .env      # then set JWT_SECRET (32+ random characters)
make up                   # Postgres and Redis
make migrate              # database migrations
make api                  # API on http://localhost:8000
make worker               # background worker
make desktop              # the desktop app
make check                # all linters and tests
```

Health check: `curl localhost:8000/api/v1/health`

Sign in during development: enter your email in the app, then open the link the API prints
in its log (the line starting `auth.magic_link`).

Chatting needs three things running: `make api`, `make worker` and `make desktop`. Without an
Anthropic API key, set `LLM_PROVIDER=fake` in `.env` to try the app with a scripted model.
