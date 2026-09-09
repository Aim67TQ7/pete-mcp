"""VPS fleet adapter — HTTP health checks only, no SSH from the gateway.
Maggie (89.116.157.23, platform), Bunting (31.220.48.32), Pete (dark per
CURRENT_PRIORITIES: terminate-or-recover). Each instance points at an env-named
health URL; an unreachable host is reported unknown, never assumed-unchanged."""
import httpx

from ..config import Settings
from . import ConnectorError, ConnectorStatus

INSTANCES = ["MAGGIE", "BUNTING", "PETE"]

OPERATIONS = {
    "health": {"write": False},    # params: none (instance selects host)
    "fleet": {"write": False},
}


def _url(host: str) -> str:
    h = (host or "").upper()
    if h not in INSTANCES:
        raise ConnectorError("unavailable", f"unknown host '{host}'. Registered: {', '.join(INSTANCES)}")
    url = Settings.secret(f"VPS_{h}_HEALTH_URL")
    if not url:
        raise ConnectorError("unconfigured", f"VPS_{h}_HEALTH_URL not set")
    return url


async def _check(host: str) -> dict:
    url = _url(host)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
        return {"host": host, "state": "up" if resp.status_code < 400 else "degraded",
                "http": resp.status_code}
    except (httpx.TimeoutException, httpx.TransportError):
        return {"host": host, "state": "unreachable"}


async def run(operation: str, params: dict, instance: str | None) -> dict:
    if operation == "fleet":
        results = []
        for h in INSTANCES:
            try:
                results.append(await _check(h))
            except ConnectorError as exc:
                results.append({"host": h, "state": exc.state})
        return {"fleet": results}
    if operation == "health":
        if instance is None:
            raise ConnectorError("unavailable", "instance (host) required: MAGGIE | BUNTING | PETE")
        return await _check(instance)
    raise ConnectorError("unavailable", f"unknown operation '{operation}'")


async def probe() -> ConnectorStatus:
    st = ConnectorStatus("vps", "unconfigured")
    states = {}
    for h in INSTANCES:
        try:
            res = await _check(h)
            states[h] = "connected" if res["state"] == "up" else "unavailable"
        except ConnectorError as exc:
            states[h] = exc.state
    st.instances = states
    if any(s == "connected" for s in states.values()):
        st.state = "connected"
    return st
