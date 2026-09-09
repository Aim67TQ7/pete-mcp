# Client connections — one endpoint, independently revocable credentials

Endpoint: `https://mcp.by-pete.com/mcp` (proposed; see DEPLOY.md). Every client
gets its own key:

```bash
python -m gateway.admin create-client claude
python -m gateway.admin grant claude platform 'memory:*,jobs:*,reports:read,connector:*:read'
python -m gateway.admin grant claude copackers 'memory:*,jobs:*'
```

Revoking one client (`python -m gateway.admin revoke chatgpt`) never disables
the others — that's the spec's acceptance test 3.

Scope grammar: `memory:read|write`, `jobs:submit`, `reports:read`,
`connector:<name>:read|write`, wildcards `memory:*`, `connector:*`, `*`.
Grant `connector:epicor:read` / PZLO access only to Bunting-side clients.

## Per-client reality (verify each account before promising)

| Client | How | Honest caveat |
|---|---|---|
| **Claude Code / Claude API** | `claude mcp add pete-gateway https://mcp.by-pete.com/mcp -t http -H "Authorization: Bearer pmk_..."` | Works today with bearer keys. |
| **claude.ai (web/desktop)** | Settings → Connectors → custom connector | The claude.ai UI drives the MCP OAuth flow; it has no raw-header field. Until the OAuth AS leg ships (below), use Claude Code / API with the bearer key. |
| **ChatGPT** | Developer mode → custom MCP connector | Verify the specific workspace supports developer-mode MCP and its approval behavior. Same OAuth caveat as claude.ai for the consumer UI. |
| **Gemini** | Gemini CLI `settings.json` → `mcpServers` with `httpUrl` + headers | CLI only; do not infer consumer-app support. |
| **Grok / xAI** | xAI API remote MCP tool definition with the URL + bearer header | API only; validate the account's options. |
| **Pete Qwen** | Any MCP client library (or plain Streamable HTTP JSON-RPC) with the bearer header | Needs its runtime integration test — acceptance step 3. |

## OAuth leg (staged, by design)

The gateway already serves `/.well-known/oauth-protected-resource` and answers
401 with `WWW-Authenticate` pointing at it. Phase 2 plugs a maintained OAuth
AS (Supabase Auth as OIDC issuer is the stack-native candidate) into
`authorization_servers`, validating issuer/audience/expiry/scopes and mapping
tokens to the same `gateway.clients` rows. Incoming MCP tokens are never
forwarded to providers — connector credentials are separate by construction.

## Cross-model memory in practice

1. Claude records: `memory_record(project="copackers", kind="fact", content="...", evidence_url="...")`
2. ChatGPT (or Pete Qwen) later runs `memory_search(project="copackers", query="...")` and sees it, tagged with author + confidence + provenance.
3. Edits go through `memory_supersede` with the expected version — a version
   conflict means another client got there first; re-read and retry.
4. Facts / decisions / suggestions stay separate kinds; memory never changes
   permissions, budgets, or recipient rules (policy tables do).

Private chat histories do not synchronize automatically — clients must
explicitly record and retrieve. To seed shared memory from ChatGPT/Claude
exports, run the existing import-memory flow against `memory_record`.

## Reporting delivery

`reports_get` (optionally `build=true`) returns the consolidated report. An
MCP server cannot initiate a ChatGPT message: point the existing scheduled
ChatGPT task at this connection and have it call `reports_get` — after
verifying that account's scheduled tasks can use custom connectors. If they
cannot, deliver via a supported channel (the Slack connector's `post_message`
is registered and one grant away).
