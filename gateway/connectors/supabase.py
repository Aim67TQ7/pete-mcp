"""Supabase multi-instance adapter (ZODA, PZLO, MCPDB) over PostgREST.

Read-only: SELECT via /rest/v1/<table> with bounded filters. Raw SQL is outside
the initial tool contract by design. PZLO stays company-scoped (Bunting only);
Philip isolation is a grant question — n0v8v/by-pete clients simply never get
connector:supabase:read on the bunting project.
"""
import httpx

from ..config import Settings
from . import ConnectorError, ConnectorStatus, classify_http

INSTANCES = ["ZODA", "PZLO", "MCPDB"]

OPERATIONS = {
    "select": {"write": False},   # params: table, columns?, filter?, limit?
    "instances": {"write": False},
}

MAX_LIMIT = 200


def _creds(instance: str) -> tuple[str, str]:
    inst = (instance or "").upper()
    if inst not in INSTANCES:
        raise ConnectorError("unavailable", f"unknown instance '{instance}'. Registered: {', '.join(INSTANCES)}")
    url = Settings.secret(f"SUPABASE_{inst}_URL")
    key = Settings.secret(f"SUPABASE_{inst}_SERVICE_KEY")
    if not url or not key:
        raise ConnectorError("unconfigured", f"SUPABASE_{inst}_URL / _SERVICE_KEY not set")
    return url.rstrip("/"), key


async def run(operation: str, params: dict, instance: str | None) -> dict:
    if operation == "instances":
        return {"instances": INSTANCES}
    if instance is None:
        raise ConnectorError("unavailable", "instance required (ZODA | PZLO | MCPDB)")
    url, key = _creds(instance)
    table = str(params.get("table", "")).strip()
    if not table.replace("_", "").isalnum():
        raise ConnectorError("unavailable", "invalid table name")
    limit = min(int(params.get("limit", 50)), MAX_LIMIT)
    query = {"select": params.get("columns", "*"), "limit": str(limit)}
    # filter: {"column": "status", "op": "eq", "value": "open"} -> status=eq.open
    filt = params.get("filter")
    if isinstance(filt, dict) and {"column", "op", "value"} <= set(filt):
        col = str(filt["column"])
        if not col.replace("_", "").isalnum():
            raise ConnectorError("unavailable", "invalid filter column")
        if filt["op"] not in {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is"}:
            raise ConnectorError("unavailable", "unsupported filter op")
        query[col] = f"{filt['op']}.{filt['value']}"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(f"{url}/rest/v1/{table}", params=query, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ConnectorError("unavailable", f"transport failure: {type(exc).__name__}")
    state = classify_http(resp.status_code)
    if state != "connected":
        raise ConnectorError(state, f"provider returned HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise ConnectorError("unavailable", f"HTTP {resp.status_code}: table missing or not exposed")
    return {"status": resp.status_code, "rows": resp.json(), "instance": instance.upper()}


async def probe() -> ConnectorStatus:
    st = ConnectorStatus("supabase", "unconfigured")
    states = {}
    for inst in INSTANCES:
        try:
            url, key = _creds(inst)
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{url}/rest/v1/",
                                        headers={"apikey": key, "Authorization": f"Bearer {key}"})
            states[inst] = classify_http(resp.status_code) if resp.status_code != 200 else "connected"
        except ConnectorError as exc:
            states[inst] = exc.state
        except Exception:
            states[inst] = "unavailable"
    st.instances = states
    if any(s == "connected" for s in states.values()):
        st.state = "connected"
    elif any(s == "reauth_required" for s in states.values()):
        st.state = "reauth_required"
    return st
