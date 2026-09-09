# PETE MCP Gateway

One remote MCP endpoint (`https://mcp.by-pete.com/mcp`, Streamable HTTP) that
gives every AI client — Claude, Claude Code, ChatGPT, Gemini CLI, Grok/xAI,
Pete Qwen — the same policy-checked business tools, shared cross-client
memory, durable jobs, and consolidated reporting across the copackers /
bypete / offduty projects plus Bunting and n0v8v operations.

Built to `docs/SPEC.md`. Status: deployment-sequence step 2 complete (isolated
gateway, auth, policy, memory, jobs, reports, connector adapters, tests);
steps 3–6 are host + credential work (`docs/DEPLOY.md`).

## Layout

| Path | What |
|---|---|
| `gateway/server.py` | MCP server (FastMCP, stateless Streamable HTTP) + bearer auth ASGI wrapper, `/healthz`, protected-resource discovery |
| `gateway/policy.py` | project × actor × action grants, daily budgets, cross-client effect keys, audit log |
| `gateway/memory.py` | shared memory: fact/decision/suggestion, provenance, optimistic versioning |
| `gateway/jobs.py` + `gateway/worker.py` | durable queue (SKIP LOCKED + leases, bounded retries), registered job types only, RULE_4 verification-or-unverified |
| `gateway/connectors/` | adapter framework; declarative REST connectors in `gateway/registry.yaml`, dedicated adapters for supabase (ZODA/PZLO/MCPDB), epicor (BMC/BME/MAI), gmail (multi-account), ms365, vps fleet |
| `gateway/admin.py` | operator CLI: create-client / grant / revoke / list |
| `migrations/` | additive `gateway` schema (applied to Supabase project `gjaerlqdnsdveoxedpgk`) |
| `docs/` | SPEC, CONNECTORS walkthrough, CLIENTS hookup guide, DEPLOY |

## Tools

`whoami`, `system_status`, `connections_status`, `connector_call`,
`memory_search`, `memory_record`, `memory_supersede`, `jobs_submit`,
`jobs_get`, `jobs_cancel`, `reports_get`.

Adding a REST connector = one entry in `gateway/registry.yaml` (env var names
only — no secret value ever appears in this repo, per SECURITY_BOUNDARIES).

## Quick start

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill server-side only
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m gateway.server
```

n0v8v LLC | GP3 methodology
