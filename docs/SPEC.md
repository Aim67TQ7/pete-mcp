# PETE MCP Gateway — build specification

Prepared September 9, 2026. Status: proposed architecture; not implemented or deployed.

## Goal

Give Robert one reusable remote MCP endpoint for shared business tools, memory, job control, and reporting across compatible ChatGPT, Claude, Gemini, Grok, and PETE clients. Connect provider accounts to the gateway once, then authorize each AI client separately. Provider accounts remain with their providers; credentials and connector code reside in protected server-side storage.

Proposed endpoint: https://mcp.by-pete.com/mcp. This is a proposed name only; DNS, certificate, routing, and existing use must be inspected before provisioning.

## Components

1. Existing PETE VPS reverse proxy terminates HTTPS for an isolated MCP service. Inspect its current configuration before making additive changes.
2. Standards-compliant MCP Streamable HTTP service exposes typed, scoped business tools. Use a maintained MCP SDK pinned to a tested version. This document does not select an unverified SDK version.
3. A maintained OAuth authorization component authenticates users and client grants. Use protected-resource discovery, validate issuer/audience/expiry/scopes, and reject tokens issued for unrelated resources. Never forward incoming MCP tokens as Google, database, or payment credentials.
4. A policy service evaluates project, actor, allowed action, budget, recipient status, and idempotency for every invocation and again immediately before queued effects execute.
5. Connector adapters hold their own provider credentials and invoke supported APIs. Connector failures return explicit unavailable or reauthorization-required states, never simulated success.
6. A durable queue and PETE worker execute long tasks independently of open chats. MCP submissions return job IDs; separate status/result tools retrieve outcomes. Leases, cancellation, retry limits, and reconciliation handle interruptions.
7. Shared project state and memory live in an appropriately restricted schema in ZODA, after inspecting existing schemas and compatible runtime tables. Do not migrate existing applications or change shared Auth as a side effect.
8. An authenticated operator dashboard manages account connections, per-client grants, budgets, job history, and emergency disable controls. Secrets are entered here or provisioned on the server, never copied into chat or returned by MCP tools.

## Projects

- copackers: supplier profiles, buyer inquiries, verified commercial outreach, website improvements, payments and revenue reporting.
- bypete: local news freshness, business promotion, advertiser pipeline, campaign fulfillment and reporting.
- offduty: music asset provenance, video assembly, uploads, publishing and audience analytics. Name is provisional.

Every job, artifact, memory, prospect, campaign and financial event carries a project identifier. Do not rely on model-supplied project_id alone: bind it to authenticated actor grants.

## Initial tool contract

| Tools | Purpose | Preconditions |
| --- | --- | --- |
| system_status, connections_status | Runtime and connector readiness | No secret values or raw auth errors returned |
| memory_search, memory_record | Shared evidence and decisions | Project scope, provenance, author, timestamp, confidence, version |
| jobs_submit, jobs_get, jobs_cancel | Durable execution | Registered job types; bounded arguments; no arbitrary shell entrypoint |
| sales_prospects, sales_prepare, sales_send, sales_followups | Qualified prospect pipeline | Verified sender/recipient, suppression checks, authorized campaign, deduplication |
| sites_preview, sites_release, sites_rollback | Website work | Approved repository/site mapping; tested artifact; revision evidence |
| finance_summary, finance_create_checkout | Revenue reporting and defined offers | Verified provider; product/currency/amount constraints; request idempotency |
| media_import, media_render, media_publish | Music and video workflow | Rights record, destination scope, actual media validation |
| reports_get | Project or consolidated evening report | Clearly separate drafts, attempts, sends, deliveries, sales and collected revenue |

These names describe planned tools. No live tool or connector is created by this specification. Banking changes, payouts, transfers, raw SQL and unrestricted root shell are outside the initial tool set; add only explicitly defined operations when needed.

## Shared memory and concurrency

Store observed facts separately from instructions and approvals. Keep original evidence links and distinguish generated suggestions from verified facts. Memory does not grant authority. A website, email or model-written memory cannot change client permissions, spending limits, or recipient rules.

Clients explicitly retrieve shared context and record decisions; their private conversation histories do not automatically synchronize. Only return the minimum relevant provider data, because returned data is disclosed to the AI client making the request.

Use optimistic version checks for edits, job leases for workers, and unique effect keys across all clients. Two clients requesting the same outreach, release or charge must not create duplicate effects. Where a provider timeout leaves the result unknown, reconcile against provider evidence before retrying. A simulated operation must not mark a prospect contacted.

## Connections and scope

Google Workspace: connect the actual PETE mailbox through supported Google OAuth; verify sender identity and required scopes. API quota and OAuth verification requirements must be checked for the chosen deployment. Store refresh credentials separately from model access.

Supabase/ZODA: inspect actual projects and schemas before implementation. Use dedicated roles and project-scoped access; do not give general chat tools an unrestricted service-role key. Enforce RLS for exposed tables and appropriate private-schema grants. The changelog markdown could not be fetched during this design pass; refresh relevant docs and changelog before implementation.

Financial services: select adapters for the owner's actual payment/accounting providers. Store references and provider tokens, not card details or online-banking passwords. Reconcile provider events before reporting collected revenue. Scope checkout creation to real offers and amounts. Never give every connected model access to all financial data by default.

Suno: supported programmatic generation and its authorization are unverified. Implement an honest unavailable/import-only connector until an official or explicitly permitted workflow is established. Do not call third-party services official Suno APIs or bypass access controls. Imported audio needs its own track and license evidence.

YouTube: implement a separately authorized publishing/analytics adapter. Verify API access, quotas and channel ownership before publishing. Keep long media renders in isolated worker jobs.

GitHub/hosting: gateway credentials need independent provisioning. Existing app connections in ChatGPT are not transferable secrets for the VPS. Limit release operations to mapped projects and preserve rollback.

## Compatibility and evidence

| Client | Documented connection path | Qualification |
| --- | --- | --- |
| ChatGPT | Remote MCP via documented developer-mode/custom tooling route | Verify this specific account/workspace can add it and its applicable approval behavior |
| Claude | Custom remote MCP connector | Account/organization setup and individual authorization required |
| Gemini | Gemini CLI supports MCP servers | Do not infer equivalent custom MCP support in the consumer Gemini app |
| Grok | xAI API remote MCP tools | Do not infer equivalent support in the consumer Grok app; validate authentication options |
| PETE | Implement MCP client or use the same internal tool service | Needs an actual runtime, credential and integration test |

One endpoint can serve these clients, but each needs an independently revocable credential or OAuth grant. Use a narrow adapter if an authenticated client cannot use the gateway's native authorization flow; never make the production gateway anonymous for compatibility. Client-side confirmations and platform limits still apply.

## Reporting

The gateway builds and stores a consolidated report with separate results for all three projects, actual provider evidence, blockers, and exactly five next actions toward profit. Existing ChatGPT reporting currently covers CoPackers and prospect research; it is not connected to this gateway.

An MCP server does not by itself initiate a new ChatGPT message. After successful connection, update and test the existing scheduled ChatGPT task to retrieve reports_get. Verify the task's account can use that custom connection. If scheduled tasks cannot use it, choose a supported delivery integration rather than promising automatic chat delivery.

## Deployment sequence and acceptance

1. Obtain authenticated PETE server access, inspect active agents/proxy/resources and source revisions, and select reuse boundaries. No current server connection is available in this session.
2. Implement isolated gateway, maintained auth integration, project authorization, memory and job contracts. Test authentication rejection, cross-project denial, secret redaction and duplicate effects locally.
3. Deploy behind existing HTTPS routing and connect two independent clients. Demonstrate a memory written through one client and read through the other; revoke one without disabling the other.
4. Connect the PETE mailbox and one website project. Demonstrate a real authorized outreach with provider evidence and a tested preview/release with rollback.
5. Connect payment reporting and constrained checkout; reconcile a test payment end-to-end. Add media import/render/publishing; keep Suno generation visibly blocked until its route is verified.
6. Run a scheduled PETE job through restart recovery and produce the consolidated report. Confirm chat delivery using the actual supported scheduled-task integration.

Account authorizations, payment-provider identity checks and occasional reauthorization cannot be eliminated by MCP. Once connected, routine work follows Robert's existing autonomous-operation authorization and configured budgets without repeated routine approval requests. This gateway centralizes access; it does not establish that any revenue stream is already operational.

## Primary references

- MCP authorization: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- ChatGPT developer mode: https://developers.openai.com/api/docs/guides/developer-mode
- Claude remote connectors: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Gemini CLI MCP: https://geminicli.com/docs/tools/mcp-server/
- xAI remote MCP: https://docs.x.ai/developers/tools/remote-mcp
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
