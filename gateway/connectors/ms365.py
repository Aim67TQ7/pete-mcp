"""Microsoft 365 adapter via Graph client-credential flow (app-only).
Covers Bunting-side Outlook/SharePoint/Teams reads once an app registration
with granted application permissions is provisioned."""
import httpx

from ..config import Settings
from . import ConnectorError, ConnectorStatus, classify_http

OPERATIONS = {
    "organization": {"write": False},
    "users_list": {"write": False},   # params: top?
}


async def _token() -> str:
    tenant = Settings.secret("MS365_TENANT_ID")
    cid = Settings.secret("MS365_CLIENT_ID")
    csec = Settings.secret("MS365_CLIENT_SECRET")
    if not all([tenant, cid, csec]):
        raise ConnectorError("unconfigured", "MS365_TENANT_ID/_CLIENT_ID/_CLIENT_SECRET not all set")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={"client_id": cid, "client_secret": csec,
                      "scope": "https://graph.microsoft.com/.default",
                      "grant_type": "client_credentials"})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ConnectorError("unavailable", f"transport failure: {type(exc).__name__}")
    if resp.status_code != 200:
        raise ConnectorError("reauth_required", "Graph token request rejected")
    return resp.json()["access_token"]


async def _graph(method: str, path: str, query=None) -> dict:
    token = await _token()
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.request(method, f"https://graph.microsoft.com/v1.0{path}",
                                        params=query, headers={"Authorization": f"Bearer {token}"})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ConnectorError("unavailable", f"transport failure: {type(exc).__name__}")
    state = classify_http(resp.status_code)
    if state != "connected":
        raise ConnectorError(state, f"Graph returned HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise ConnectorError("unavailable", f"Graph returned HTTP {resp.status_code}")
    return resp.json()


async def run(operation: str, params: dict, instance: str | None) -> dict:
    if operation == "organization":
        data = await _graph("GET", "/organization")
        return {"organizations": [o.get("displayName") for o in data.get("value", [])]}
    if operation == "users_list":
        data = await _graph("GET", "/users", query={"$top": min(int(params.get("top", 10)), 50)})
        return {"users": [{"name": u.get("displayName"), "mail": u.get("mail")}
                          for u in data.get("value", [])]}
    raise ConnectorError("unavailable", f"unknown operation '{operation}'")


async def probe() -> ConnectorStatus:
    try:
        await _token()
        return ConnectorStatus("ms365", "connected")
    except ConnectorError as exc:
        return ConnectorStatus("ms365", exc.state, str(exc))
    except Exception as exc:
        return ConnectorStatus("ms365", "unavailable", type(exc).__name__)
