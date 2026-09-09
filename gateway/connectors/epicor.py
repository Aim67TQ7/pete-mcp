"""Epicor adapter — all companies (BMC, BME, MAI), GET-only OData against
pre-built BAQs. No Epicor core modifications; basic auth + per-company API key,
matching the existing Caddy-proxy pattern. Bunting-domain data: grants must
keep this on the 'bunting' project only (Philip isolation)."""
import httpx

from ..config import Settings
from . import ConnectorError, ConnectorStatus, classify_http

INSTANCES = ["BMC", "BME", "MAI"]

OPERATIONS = {
    "baq_get": {"write": False},   # params: baq, top?, filter?, select?
    "companies": {"write": False},
}

MAX_TOP = 500


def _conn(company: str) -> tuple[str, tuple[str, str], str]:
    co = (company or "").upper()
    if co not in INSTANCES:
        raise ConnectorError("unavailable", f"unknown company '{company}'. Registered: {', '.join(INSTANCES)}")
    base = Settings.secret("EPICOR_BASE_URL")
    user = Settings.secret("EPICOR_USER")
    pw = Settings.secret("EPICOR_PASSWORD")
    key = Settings.secret(f"EPICOR_API_KEY_{co}")
    if not all([base, user, pw, key]):
        raise ConnectorError("unconfigured", f"EPICOR_BASE_URL/_USER/_PASSWORD/_API_KEY_{co} not all set")
    return base.rstrip("/"), (user, pw), key


async def run(operation: str, params: dict, instance: str | None) -> dict:
    if operation == "companies":
        return {"companies": INSTANCES}
    if instance is None:
        raise ConnectorError("unavailable", "instance (company) required: BMC | BME | MAI")
    base, auth, key = _conn(instance)
    baq = str(params.get("baq", "")).strip()
    if not baq or not all(c.isalnum() or c in "_-." for c in baq):
        raise ConnectorError("unavailable", "invalid BAQ id")
    query: dict = {"$top": str(min(int(params.get("top", 100)), MAX_TOP))}
    if params.get("filter"):
        query["$filter"] = str(params["filter"])
    if params.get("select"):
        query["$select"] = str(params["select"])
    url = f"{base}/api/v2/odata/{instance.upper()}/BaqSvc/{baq}/Data"
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(url, params=query, auth=auth, headers={"X-API-Key": key})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ConnectorError("unavailable", f"transport failure: {type(exc).__name__}")
    state = classify_http(resp.status_code)
    if state != "connected":
        raise ConnectorError(state, f"Epicor returned HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise ConnectorError("unavailable", f"Epicor returned HTTP {resp.status_code} (bad BAQ or filter)")
    data = resp.json()
    rows = data.get("value", data)
    return {"status": resp.status_code, "company": instance.upper(), "baq": baq,
            "partial": resp.status_code == 206, "rows": rows}


async def probe() -> ConnectorStatus:
    st = ConnectorStatus("epicor", "unconfigured")
    states = {}
    for co in INSTANCES:
        try:
            base, auth, key = _conn(co)
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(f"{base}/api/v2/odata/{co}", auth=auth,
                                        headers={"X-API-Key": key})
            states[co] = "connected" if resp.status_code < 400 else classify_http(resp.status_code)
        except ConnectorError as exc:
            states[co] = exc.state
        except Exception:
            states[co] = "unavailable"
    st.instances = states
    if any(s == "connected" for s in states.values()):
        st.state = "connected"
    elif any(s == "reauth_required" for s in states.values()):
        st.state = "reauth_required"
    return st
