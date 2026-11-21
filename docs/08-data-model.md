# 08. Data model (Postgres)

All ids are UUID v7. All tables have `created_at` and `updated_at` (timestamptz). Every row that belongs to a user has `user_id` and every query filters by it.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
  id uuid PRIMARY KEY,
  email citext UNIQUE NOT NULL,
  name text,
  avatar_url text,
  timezone text NOT NULL DEFAULT 'UTC',
  daily_token_budget bigint NOT NULL DEFAULT 2000000,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash text NOT NULL,             -- sha256, never the raw token
  device_name text,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);

CREATE TABLE bots (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name text NOT NULL,
  avatar text,                          -- emoji or image URL
  job text NOT NULL,                    -- one line
  instructions text NOT NULL DEFAULT '',
  approval_mode text NOT NULL DEFAULT 'ask_risky',   -- always_ask | ask_risky | never_ask
  is_primary boolean NOT NULL DEFAULT false,
  enabled_tools text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX one_primary_bot ON bots(user_id) WHERE is_primary;

CREATE TABLE chats (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind text NOT NULL,                   -- direct | group
  title text,
  last_message_at timestamptz
);
CREATE TABLE chat_members (
  chat_id uuid REFERENCES chats(id) ON DELETE CASCADE,
  bot_id uuid REFERENCES bots(id) ON DELETE CASCADE,
  PRIMARY KEY (chat_id, bot_id)
);

CREATE TABLE messages (
  id uuid PRIMARY KEY,
  chat_id uuid NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role text NOT NULL,                   -- user | bot | system
  bot_id uuid REFERENCES bots(id),
  content text NOT NULL,
  card jsonb,                           -- approval / page / file card payload
  run_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON messages(chat_id, created_at DESC);

CREATE TABLE runs (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  chat_id uuid REFERENCES chats(id) ON DELETE SET NULL,
  routine_id uuid,
  status text NOT NULL,                 -- queued | running | waiting_approval | paused | completed | failed | cancelled | needs_review
  steps int NOT NULL DEFAULT 0,
  input_tokens bigint NOT NULL DEFAULT 0,
  output_tokens bigint NOT NULL DEFAULT 0,
  error text,
  started_at timestamptz,
  finished_at timestamptz
);

CREATE TABLE tool_calls (
  id uuid PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  tool text NOT NULL,
  args jsonb NOT NULL,                  -- with vault placeholders, never raw secrets
  risk text NOT NULL,                   -- safe | risky
  status text NOT NULL,                 -- pending | waiting_approval | running | ok | error | rejected
  result_summary text,
  result_ref text,                      -- pointer to large output in object storage
  started_at timestamptz,
  finished_at timestamptz
);

CREATE TABLE approvals (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  tool_call_id uuid NOT NULL REFERENCES tool_calls(id) ON DELETE CASCADE,
  bot_id uuid NOT NULL REFERENCES bots(id),
  title text NOT NULL,                  -- "Send email to sam@acme.com"
  preview jsonb NOT NULL,               -- what the user sees and can edit
  status text NOT NULL DEFAULT 'pending',   -- pending | approved | rejected | expired
  edited_args jsonb,
  resolved_at timestamptz
);

CREATE TABLE memories (
  id uuid PRIMARY KEY,
  bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text text NOT NULL,
  embedding vector(1024)                -- optional, for search later
);

CREATE TABLE skills (
  id uuid PRIMARY KEY,
  bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  slug text NOT NULL,                   -- used after "/" in the composer
  name text NOT NULL,
  description text NOT NULL,
  steps text NOT NULL,                  -- markdown
  rules text NOT NULL DEFAULT '',
  UNIQUE (bot_id, slug)
);

CREATE TABLE routines (
  id uuid PRIMARY KEY,
  bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  skill_id uuid NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  trigger jsonb NOT NULL,               -- {type:"cron",cron,timezone} | {type:"webhook"} | {type:"connector_event",...}
  webhook_secret_hash text,
  notify boolean NOT NULL DEFAULT false,
  paused boolean NOT NULL DEFAULT false,
  next_run_at timestamptz
);
CREATE INDEX ON routines(next_run_at) WHERE NOT paused;

CREATE TABLE connectors (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind text NOT NULL,                   -- gmail | gcal | slack | notion | github | mcp
  name text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}',   -- MCP URL, Composio connection id; no secrets
  secret_id uuid,                       -- vault item for tokens/headers
  status text NOT NULL DEFAULT 'connected'
);

CREATE TABLE vault_items (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name text NOT NULL,                   -- used in {{vault:name}}
  type text NOT NULL,                   -- login | api_key | card | note | oauth_token
  ciphertext bytea NOT NULL,            -- AES-256-GCM
  nonce bytea NOT NULL,
  wrapped_data_key bytea NOT NULL,      -- KMS-wrapped per-item key
  UNIQUE (user_id, name)
);

CREATE TABLE library_items (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  bot_id uuid REFERENCES bots(id) ON DELETE SET NULL,
  run_id uuid REFERENCES runs(id) ON DELETE SET NULL,
  kind text NOT NULL,                   -- file | page | result
  title text NOT NULL,
  path text,                            -- /workspace/outputs/...
  storage_key text,                     -- copy in object storage for download
  mime text,
  size_bytes bigint
);

CREATE TABLE computers (
  id uuid PRIMARY KEY,
  user_id uuid UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider text NOT NULL,               -- docker | e2b
  external_id text,
  status text NOT NULL DEFAULT 'stopped',  -- starting | running | paused | stopped | error
  control_token_hash text,
  last_active_at timestamptz
);

CREATE TABLE usage_daily (
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  day date NOT NULL,
  input_tokens bigint NOT NULL DEFAULT 0,
  output_tokens bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day)
);

CREATE TABLE audit_log (
  id uuid PRIMARY KEY,
  user_id uuid,
  actor text NOT NULL,                  -- user | bot:<id> | system
  action text NOT NULL,
  target text,
  detail jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

## Rules

- Keep only the last 20 runs per routine (cleanup job runs hourly).
- Store large tool outputs and files in object storage (S3 or MinIO in dev), keep a pointer in the row.
- Never store raw secrets outside `vault_items.ciphertext`.
