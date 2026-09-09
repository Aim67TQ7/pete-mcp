-- PETE MCP Gateway schema. Additive only: lives in its own `gateway` schema on
-- the Supabase "MCP" project (gjaerlqdnsdveoxedpgk). The existing public.*
-- tables (tenants, mcp_memory_chunks, ...) belong to another running app and
-- are not touched. Bridge reads happen in application code, not FKs.

create schema if not exists gateway;

-- AI clients that hold a revocable credential to this gateway
-- (claude, claude-code, chatgpt, gemini-cli, grok, pete-qwen, ...).
create table if not exists gateway.clients (
  id            uuid primary key default gen_random_uuid(),
  name          text not null unique,
  key_hash      text not null unique,           -- sha256 of the bearer key; raw key never stored
  status        text not null default 'active' check (status in ('active','revoked')),
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz
);

-- What a client may do, per project. Memory never grants authority; this table does.
create table if not exists gateway.grants (
  id                    uuid primary key default gen_random_uuid(),
  client_id             uuid not null references gateway.clients(id) on delete cascade,
  project               text not null,          -- copackers | bypete | offduty | bunting | n0v8v | platform
  scopes                text[] not null default '{}',
  daily_action_cap      int  not null default 500,
  daily_spend_cap_cents int  not null default 0,
  created_at            timestamptz not null default now(),
  unique (client_id, project)
);

create table if not exists gateway.budget_usage (
  grant_id    uuid not null references gateway.grants(id) on delete cascade,
  usage_date  date not null,
  actions     int  not null default 0,
  spend_cents int  not null default 0,
  primary key (grant_id, usage_date)
);

-- Unique effect keys across all clients: two clients requesting the same
-- outreach/release/charge collapse onto one effect.
create table if not exists gateway.effects (
  effect_key  text primary key,
  client_id   uuid references gateway.clients(id),
  project     text not null,
  action      text not null,
  result_json jsonb,
  created_at  timestamptz not null default now()
);

-- Shared cross-client memory. Facts separate from decisions/suggestions;
-- provenance mandatory; optimistic version checks for edits.
create table if not exists gateway.memories (
  id            uuid primary key default gen_random_uuid(),
  project       text not null,
  kind          text not null check (kind in ('fact','decision','suggestion')),
  content       text not null,
  evidence_url  text,
  author        text not null,                  -- client name that recorded it
  confidence    real not null default 0.5 check (confidence between 0 and 1),
  version       int  not null default 1,
  superseded_by uuid references gateway.memories(id),
  status        text not null default 'active' check (status in ('active','superseded','retracted')),
  tags          text[] not null default '{}',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  search        tsvector generated always as (to_tsvector('english', content)) stored
);
create index if not exists memories_search_idx  on gateway.memories using gin (search);
create index if not exists memories_project_idx on gateway.memories (project, status, created_at desc);

-- Durable job queue. Statuses follow RULE_4 (AGENT_SUCCESS_PATTERN).
create table if not exists gateway.jobs (
  id               uuid primary key default gen_random_uuid(),
  project          text not null,
  job_type         text not null,               -- registered types only; no arbitrary shell
  args_json        jsonb not null default '{}',
  status           text not null default 'pending'
                   check (status in ('pending','running','success','partial','unverified','error','timeout','killed','cancelled')),
  priority         int  not null default 5,
  attempts         int  not null default 0,
  max_attempts     int  not null default 3,
  lease_expires_at timestamptz,
  effect_key       text unique,
  submitted_by     text not null,
  result_json      jsonb,
  verification_json jsonb,                      -- source_of_truth + observation, mandatory for success
  error            text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists jobs_claim_idx on gateway.jobs (status, priority, created_at);

create table if not exists gateway.audit_log (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  client_name text,
  project     text,
  tool        text not null,
  action      text,
  allowed     boolean not null,
  detail_json jsonb
);
create index if not exists audit_at_idx on gateway.audit_log (at desc);

create table if not exists gateway.reports (
  id          uuid primary key default gen_random_uuid(),
  report_date date not null,
  scope       text not null default 'consolidated',
  body_json   jsonb not null,
  created_at  timestamptz not null default now(),
  unique (report_date, scope)
);

-- Deny-by-default: the gateway connects with a dedicated role over direct
-- Postgres. PostgREST does not expose this schema; RLS with no policies
-- blocks any non-owner role that ever reaches it anyway.
alter table gateway.clients      enable row level security;
alter table gateway.grants       enable row level security;
alter table gateway.budget_usage enable row level security;
alter table gateway.effects      enable row level security;
alter table gateway.memories     enable row level security;
alter table gateway.jobs         enable row level security;
alter table gateway.audit_log    enable row level security;
alter table gateway.reports      enable row level security;

revoke all on all tables in schema gateway from anon, authenticated;
alter default privileges in schema gateway revoke all on tables from anon, authenticated;
