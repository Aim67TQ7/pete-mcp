# Connector walkthrough

One gateway, two sides. **Clients** (Claude, ChatGPT, Gemini CLI, Grok/xAI,
Pete Qwen, Claude Code) connect *to* the gateway, each holding one revocable
`pmk_` key — see CLIENTS.md. **Connectors** are the provider accounts the
gateway holds server-side and exposes as policy-checked tools. This file is
the connector side, reconciled against the live inventory on 2026-09-09.

States reported by `connections_status`: `connected` | `unconfigured` |
`reauth_required` | `unavailable`. Never simulated success, never raw auth
errors, never secret values.

## Verified working (probed live 2026-09-09, HTTP 200)

| Connector | Instances | Evidence | Gateway ops |
|---|---|---|---|
| GitHub | Aim67TQ7 | `/user` 200 | whoami, repos_list, repo_get, issues_list, issue_create (write) |
| HubSpot | n0v8v CRM | contacts 200 | contacts/companies/deals list+search, contact_create (write) |
| Epicor | BMC, BME, MAI | prod OData 200 (BMC) | baq_get (GET-only OData against pre-built BAQs, per-company API key) |
| Supabase | PZLO, ZODA, MCPDB | REST 200 (PZLO, ZODA) | select (bounded PostgREST reads, no raw SQL) |
| HeyGen | — | quota 200 | quota, videos_list |

The credentials used for those probes were pasted into chat and are **burned**
(SECURITY_BOUNDARIES rule). Rotate every one, then place the rotated values in
the server-side `.env` — the probes prove the integration path, not that the
old keys should live on.

## Connected in the claude.ai org (inventory 2026-09-09), pending gateway env

| Connector | claude.ai state | Gateway requirement |
|---|---|---|
| Gmail | connected | Google OAuth client + refresh token per mailbox (`GMAIL_PETE_*`, `GMAIL_LEAN_*`). The claude.ai Gmail connector grant is **not transferable**; the gateway needs its own supported Google OAuth authorization for the actual PETE mailbox, with verified sender identity. |
| Microsoft 365 | connected | Graph app registration, client-credential flow (`MS365_*`). Covers Bunting Outlook/SharePoint/Teams reads. |
| Netlify | connected | Personal access token (`NETLIFY_TOKEN`) — sites_list, site_get, deploys_list back the future sites_preview/release/rollback tools. |
| Slack | connected | Bot token (`SLACK_BOT_TOKEN`) — auth_test, post_message (write). |
| Make | connected | API token (`MAKE_API_TOKEN`). |
| Google Drive / Calendar | connected | Same Google OAuth apparatus as Gmail; add scopes to the same client when needed. |
| Supabase / HeyGen | connected | Already verified above; provision env values after rotation. |

## Needs reconnect / unauthenticated in the org

| Connector | State | Note |
|---|---|---|
| Epicor (claude.ai connector) | needs_reconnect | Irrelevant to the gateway — the gateway talks to Epicor prod OData directly (verified working). Reconnect the claude.ai one only if you still want Epicor inside claude.ai chats without the gateway. |
| Stripe | state unknown | Gateway needs `STRIPE_API_KEY` (restricted key, read-mostly). checkout_create deliberately unregistered until offers are defined (spec: constrained checkout only). |
| HubSpot (claude.ai) | state unknown | Gateway path verified with the PAT; claude.ai connector state is separate. |
| Cloudflare, Canva, Hugging Face, Indeed, Invideo, Lovable, Semrush, rbn8n | various | Cloudflare is registered in the gateway (token verify + zones). The rest are claude.ai-side conveniences; add registry entries only when a project needs them — a YAML entry each, no code. |

## Deliberately NOT connectors

- **ChatGPT, Claude, Gemini, Grok, Pete Qwen** — these are clients. Cross-model
  memory happens because each of them reads/writes the same `memory_*` tools,
  not because the gateway calls their APIs. (LLM API keys exist in the env for
  *worker* jobs — Flash workers / Sonnet planners — not as connectors.)
- **Suno** — no verified programmatic route; honest import-only stance per spec.
- **Banking / payouts / raw SQL / shell** — outside the tool contract by design.

## Isolation rules enforced by grants

- Epicor + PZLO ride the `bunting` project. Clients serving n0v8v / by-pete /
  GP3 (including any Philip-facing client) simply never receive
  `connector:epicor:*` or supabase PZLO access on their grants.
- `gmail send`, `slack post_message`, `github issue_create`, `hubspot
  contact_create` are write ops: they demand a `connector:<name>:write` scope
  AND an `effect_key`, so two clients asking for the same outreach collapse to
  one send.

## VPS services

`vps` connector does HTTP health checks only (no SSH from the gateway):
MAGGIE (89.116.157.23), BUNTING (31.220.48.32), PETE (dark; P0
terminate-or-recover — expect `unreachable` = unknown, not assumed-unchanged).
Point `VPS_*_HEALTH_URL` at each host's existing health endpoint.
