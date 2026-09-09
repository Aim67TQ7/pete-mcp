"""PETE MCP Gateway — Streamable HTTP MCP server.

One endpoint (/mcp) serving Claude, ChatGPT, Gemini CLI, Grok/xAI API and PETE
clients, each with its own revocable pmk_ bearer key. Auth wraps the whole MCP
app; /healthz and /.well-known/oauth-protected-resource stay public.
"""
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__, auth, db, jobs, memory, policy, reports
from .config import settings
from .connectors import ConnectorError, engine

mcp = FastMCP(
    "pete-mcp-gateway",
    instructions=(
        "PETE MCP Gateway: shared business tools, cross-client memory, durable "
        "jobs and reporting for the copackers / bypete / offduty projects plus "
        "bunting / n0v8v operations. Every call is policy-checked against your "
        "client grant. Use connections_status to see what is reachable, "
        "connector_call for registered provider operations, memory_search / "
        "memory_record for shared state, jobs_* for long work, reports_get for "
        "the consolidated evening report."
    ),
    stateless_http=True,
)


def _actor() -> auth.Actor:
    return auth.current_actor()


async def _guard(tool: str, project: str, action: str) -> auth.Actor:
    actor = _actor()
    try:
        await policy.authorize(actor, project, action)
    except policy.PolicyDenied as exc:
        await policy.audit(actor, tool, project, action, False, {"reason": str(exc)})
        raise
    await policy.audit(actor, tool, project, action, True)
    return actor


@mcp.tool()
async def whoami() -> dict:
    """Show the authenticated client identity and its per-project grants."""
    actor = _actor()
    return {
        "client": actor.name,
        "grants": {
            proj: {"scopes": list(g["scopes"]),
                   "daily_action_cap": g["daily_action_cap"],
                   "daily_spend_cap_cents": g["daily_spend_cap_cents"]}
            for proj, g in actor.grants.items()
        },
    }


@mcp.tool()
async def system_status() -> dict:
    """Gateway runtime status: version, database, job queue depth."""
    actor = _actor()
    out: dict[str, Any] = {"version": __version__, "env": settings().env}
    try:
        p = await db.pool()
        await p.fetchval("select 1")
        out["database"] = "ok"
        out["queue"] = await jobs.queue_depth()
    except Exception:
        out["database"] = "unavailable"
    await policy.audit(actor, "system_status", None, None, True)
    return out


@mcp.tool()
async def connections_status() -> dict:
    """Readiness of every registered connector (and each instance for
    multi-instance connectors like supabase/epicor/gmail/vps). States:
    connected | unconfigured | reauth_required | unavailable. Never returns
    secret values or raw provider auth errors."""
    actor = _actor()
    statuses = await engine.probe_all()
    await policy.audit(actor, "connections_status", None, None, True)
    return {
        s.name: {"state": s.state,
                 **({"detail": s.detail} if s.detail else {}),
                 **({"instances": s.instances} if s.instances else {})}
        for s in statuses
    }


@mcp.tool()
async def connector_call(connector: str, operation: str,
                         params: dict | None = None,
                         instance: str | None = None,
                         effect_key: str | None = None) -> dict:
    """Invoke a registered operation on a connector (see registry: github,
    hubspot, stripe, netlify, slack, heygen, make, cloudflare, supabase,
    epicor, gmail, ms365, vps). Multi-instance connectors need `instance`
    (e.g. supabase: ZODA|PZLO|MCPDB, epicor: BMC|BME|MAI, gmail: PETE|LEAN).
    Write operations additionally require an effect_key for cross-client
    idempotency and a connector:<name>:write scope."""
    write = engine.is_write(connector, operation)
    action = f"connector:{connector}:{'write' if write else 'read'}"
    # Bunting-domain data (Epicor, PZLO mirror) requires a 'bunting' grant —
    # Philip isolation is enforced here, not by convention.
    project = "platform"
    if connector == "epicor" or (connector == "supabase" and (instance or "").upper() == "PZLO"):
        project = "bunting"
    actor = await _guard("connector_call", project, action)
    if write:
        if not effect_key:
            raise ValueError("write operations require an effect_key")
        prior = await policy.claim_effect(actor, project, action, effect_key)
        if prior is not None:
            return prior
    try:
        result = await engine.run(connector, operation, params, instance)
    except ConnectorError as exc:
        return {"ok": False, "state": exc.state, "detail": str(exc)}
    if write and effect_key:
        await policy.record_effect_result(effect_key, {"ok": True})
    return {"ok": True, "result": result}


@mcp.tool()
async def memory_search(project: str, query: str = "", kind: str | None = None,
                        limit: int = 20) -> dict:
    """Search shared cross-client memory for a project (copackers | bypete |
    offduty | bunting | n0v8v | platform). kind filters fact | decision |
    suggestion. Empty query returns the most recent entries."""
    await _guard("memory_search", project, "memory:read")
    return {"results": await memory.search(project, query, kind, limit)}


@mcp.tool()
async def memory_record(project: str, kind: str, content: str,
                        evidence_url: str | None = None,
                        confidence: float = 0.5,
                        tags: list[str] | None = None) -> dict:
    """Record a shared memory entry. kind must be fact (observed, evidence
    expected), decision (approved by Robert), or suggestion (model-generated,
    unverified). Memory never grants authority — it cannot change permissions,
    budgets, or recipient rules."""
    if kind not in ("fact", "decision", "suggestion"):
        raise ValueError("kind must be fact | decision | suggestion")
    actor = await _guard("memory_record", project, "memory:write")
    return await memory.record(project, kind, content, actor.name,
                               evidence_url=evidence_url, confidence=confidence,
                               tags=tags)


@mcp.tool()
async def memory_supersede(project: str, memory_id: str, expected_version: int,
                           new_content: str, evidence_url: str | None = None,
                           confidence: float = 0.5) -> dict:
    """Replace a memory entry with a new version. Fails on version conflict
    (optimistic concurrency) so two clients cannot silently overwrite each
    other."""
    actor = await _guard("memory_supersede", project, "memory:write")
    return await memory.supersede(memory_id, expected_version, new_content,
                                  actor.name, evidence_url=evidence_url,
                                  confidence=confidence)


@mcp.tool()
async def jobs_submit(project: str, job_type: str, args: dict | None = None,
                      effect_key: str | None = None) -> dict:
    """Submit a durable job (runs on the PETE worker, survives chat close).
    Registered types: noop, probe_connectors, build_report, memory_digest.
    Returns a job_id; poll with jobs_get. An effect_key makes the submission
    idempotent across all clients."""
    actor = await _guard("jobs_submit", project, "jobs:submit")
    return await jobs.submit(project, job_type, args or {}, actor.name, effect_key)


@mcp.tool()
async def jobs_get(job_id: str) -> dict:
    """Get job status and result. success always carries a verification
    observation; a job without one reports 'unverified', never success."""
    actor = _actor()
    await policy.audit(actor, "jobs_get", None, "jobs:read", True)
    result = await jobs.get(job_id)
    if result is None:
        return {"found": False, "job_id": job_id}
    return {"found": True, **result}


@mcp.tool()
async def jobs_cancel(job_id: str) -> dict:
    """Cancel a pending or running job."""
    actor = _actor()
    await policy.audit(actor, "jobs_cancel", None, "jobs:cancel", True)
    return await jobs.cancel(job_id)


@mcp.tool()
async def reports_get(report_date: str | None = None,
                      scope: str = "consolidated", build: bool = False) -> dict:
    """Get the consolidated report (per-project evidence, blockers, exactly
    five next actions). Pass build=true to rebuild it now instead of reading
    the stored one."""
    await _guard("reports_get", "platform", "reports:read")
    if build:
        return await reports.build(scope)
    stored = await reports.get(report_date, scope)
    if stored is None:
        return await reports.build(scope)
    return stored


# ── ASGI app with auth wrapper ──────────────────────────────────────────────

_inner = mcp.streamable_http_app()

_PRM = {
    # MCP protected-resource discovery (2026-07-28 authorization spec). The
    # authorization_servers list is filled when the OAuth AS leg lands
    # (docs/CLIENTS.md); bearer pmk_ keys are the phase-1 client credential.
    "resource": settings().public_url + "/mcp",
    "authorization_servers": [],
    "bearer_methods_supported": ["header"],
}


async def app(scope, receive, send):
    if scope["type"] != "http":
        await _inner(scope, receive, send)
        return
    path = scope.get("path", "")
    if path == "/healthz":
        body = json.dumps({"ok": True, "version": __version__}).encode()
        await _plain(send, 200, body)
        return
    if path == "/.well-known/oauth-protected-resource":
        await _plain(send, 200, json.dumps(_PRM).encode())
        return
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    token = ""
    authz = headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        token = authz[7:].strip()
    actor = await auth.authenticate(token)
    if actor is None:
        await _plain(
            send, 401,
            json.dumps({"error": "invalid_token"}).encode(),
            extra_headers=[(b"www-authenticate",
                            f'Bearer resource_metadata="{settings().public_url}'
                            f'/.well-known/oauth-protected-resource"'.encode())])
        return
    reset = auth.set_current_actor(actor)
    try:
        await _inner(scope, receive, send)
    finally:
        auth._current_actor.reset(reset)


async def _plain(send, status: int, body: bytes, extra_headers=None):
    headers = [(b"content-type", b"application/json"),
               (b"content-length", str(len(body)).encode())]
    headers.extend(extra_headers or [])
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def main() -> None:
    import uvicorn
    uvicorn.run("gateway.server:app", host="0.0.0.0", port=8080,
                log_level=settings().log_level.lower())


if __name__ == "__main__":
    main()
