# Deployment

## Host decision (open, flagged)

The spec proposes the Pete VPS reverse proxy, but CURRENT_PRIORITIES has Pete
(187.77.28.22) dark with a P0 terminate-or-recover decision pending.
Recommendation: deploy on **Maggie** (89.116.157.23) behind its existing Caddy
and keep the `mcp.by-pete.com` name — DNS just points at Maggie. Inspect
current Caddy config and DNS before provisioning (spec requirement); the
Caddyfile snippet in `deploy/` is additive.

## Database

Gateway state lives in the `gateway` schema of the Supabase **MCP** project
(`gjaerlqdnsdveoxedpgk`). Migration `migrations/001_gateway_schema.sql` was
applied 2026-09-09 via the Supabase management API — additive only; the
existing `public.*` app tables (tenants, mcp_memory_chunks, mcp_tool_runs, …)
are untouched. `DATABASE_URL` should use the project's **session pooler**
string with a dedicated role, not the service role. Grant that role usage on
the `gateway` schema only:

```sql
create role pete_gateway login password '<set on host, never in git>';
grant usage on schema gateway to pete_gateway;
grant select, insert, update on all tables in schema gateway to pete_gateway;
alter default privileges in schema gateway grant select, insert, update on tables to pete_gateway;
```

Bridge note: `public.mcp_memory_chunks` (tenant-scoped, with provenance and
verification states) predates this gateway and stays owned by its app. A
future federated `memory_search` can UNION it in read-only; do not write to it
from the gateway.

## Steps

1. Clone on the host, `cp .env.example .env`, fill values from the credential
   store (rotated values only — see the burn notice in CONNECTORS.md).
2. `docker compose up -d --build` → gateway on 127.0.0.1:8091 + worker.
3. Append `deploy/Caddyfile.snippet` to the host Caddyfile, reload Caddy.
4. `curl https://mcp.by-pete.com/healthz` → `{"ok": true}`.
5. Create clients + grants (`gateway.admin`), connect two independent clients,
   run the acceptance sequence from the spec (memory written by one, read by
   the other; revoke one, other keeps working).
6. Submit `jobs_submit(project="platform", job_type="probe_connectors")`,
   restart the worker container mid-run, confirm the lease recovers the job.

## Local validation (already run in CI/dev)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest pytest-asyncio
.venv/bin/python -m pytest tests/ -q       # 19 passed
.venv/bin/python -m gateway.server         # /healthz 200, /mcp -> 401 without key
```
