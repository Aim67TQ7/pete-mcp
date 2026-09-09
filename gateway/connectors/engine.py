"""Declarative HTTP connector engine + dispatcher for adapter modules.

Everything registered in registry.yaml is invocable through exactly one path:
run(connector, operation, params, instance). Unregistered operations fail with
the list of registered ones; provider bodies are truncated; secrets never leave
the process.
"""
import asyncio
import importlib
from pathlib import Path
from typing import Any

import httpx
import yaml

from ..config import Settings
from . import ConnectorError, ConnectorStatus, classify_http

_REGISTRY: dict | None = None
TIMEOUT = 25.0
MAX_BODY = 20_000  # cap provider payloads returned to clients


def registry() -> dict:
    global _REGISTRY
    if _REGISTRY is None:
        path = Path(__file__).resolve().parent.parent / "registry.yaml"
        _REGISTRY = yaml.safe_load(path.read_text())["connectors"]
    return _REGISTRY


def connector_names() -> list[str]:
    return sorted(registry().keys())


def _auth_headers(spec: dict) -> dict[str, str]:
    auth = spec.get("auth", {})
    style = auth.get("style", "none")
    if style == "none":
        return {}
    secret = Settings.secret(auth["env"])
    if secret is None:
        raise ConnectorError("unconfigured", f"env {auth['env']} not set")
    if style == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if style == "header":
        return {auth["header"]: auth.get("prefix", "") + secret}
    raise ConnectorError("unavailable", f"unknown auth style {style}")


def _truncate(body: Any) -> Any:
    s = body if isinstance(body, str) else None
    if s is not None and len(s) > MAX_BODY:
        return s[:MAX_BODY] + "…[truncated]"
    return body


async def _http_call(spec: dict, method: str, path: str, *,
                     query: dict | None = None, body: dict | None = None) -> dict:
    headers = _auth_headers(spec)
    headers.update(spec.get("headers", {}))
    url = spec["base_url"].rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.request(method, url, params=query or None,
                                        json=body if body else None, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ConnectorError("unavailable", f"transport failure: {type(exc).__name__}")
    state = classify_http(resp.status_code)
    if state != "connected":
        # No raw provider auth errors returned (spec requirement).
        raise ConnectorError(state, f"provider returned HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise ConnectorError("unavailable", f"provider returned HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError:
        payload = resp.text
    return {"status": resp.status_code, "data": _truncate(payload)}


def _adapter(module_name: str):
    return importlib.import_module(f".{module_name}", package=__package__)


def operation_spec(connector: str, operation: str) -> tuple[dict, dict]:
    """Return (connector_spec, op_spec) for a registered http op, else raise."""
    spec = registry().get(connector)
    if spec is None:
        raise ConnectorError("unavailable", f"unknown connector '{connector}'. "
                             f"Registered: {', '.join(connector_names())}")
    if spec.get("kind") == "adapter":
        mod = _adapter(spec["module"])
        ops = getattr(mod, "OPERATIONS", {})
        if operation not in ops:
            raise ConnectorError("unavailable",
                                 f"unknown operation '{operation}' for {connector}. "
                                 f"Registered: {', '.join(sorted(ops))}")
        return spec, {"adapter": True, "write": ops[operation].get("write", False)}
    ops = spec.get("operations", {})
    if operation not in ops:
        raise ConnectorError("unavailable",
                             f"unknown operation '{operation}' for {connector}. "
                             f"Registered: {', '.join(sorted(ops))}")
    return spec, ops[operation]


def is_write(connector: str, operation: str) -> bool:
    _, op = operation_spec(connector, operation)
    return bool(op.get("write", False))


async def run(connector: str, operation: str, params: dict[str, Any] | None = None,
              instance: str | None = None) -> dict:
    params = params or {}
    spec, op = operation_spec(connector, operation)
    if spec.get("kind") == "adapter":
        mod = _adapter(spec["module"])
        return await mod.run(operation, params, instance)
    # Declarative HTTP operation: substitute path params, pass allowed query/body.
    path = op["path"]
    allowed = set(op.get("params", []))
    body_keys = set(op.get("body", []))
    query: dict = {}
    for key, val in params.items():
        placeholder = "{" + key + "}"
        if placeholder in path:
            path = path.replace(placeholder, str(val))
        elif key in body_keys:
            continue
        elif key in allowed:
            query[key] = val
        else:
            raise ConnectorError("unavailable",
                                 f"parameter '{key}' not registered for {connector}.{operation}")
    if "{" in path:
        raise ConnectorError("unavailable", f"missing path parameter in '{op['path']}'")
    query.update(op.get("query", {}))
    body = {k: params[k] for k in body_keys if k in params} or None
    return await _http_call(spec, op["method"], path, query=query, body=body)


async def probe(connector: str) -> ConnectorStatus:
    spec = registry().get(connector)
    if spec is None:
        return ConnectorStatus(connector, "unavailable", "not registered")
    if spec.get("kind") == "adapter":
        try:
            return await _adapter(spec["module"]).probe()
        except ConnectorError as exc:
            return ConnectorStatus(connector, exc.state, str(exc))
        except Exception as exc:
            return ConnectorStatus(connector, "unavailable", type(exc).__name__)
    pr = spec.get("probe")
    if pr is None:
        return ConnectorStatus(connector, "unconfigured", "no probe defined")
    try:
        await _http_call(spec, pr["method"], pr["path"], query=pr.get("query"))
        return ConnectorStatus(connector, "connected")
    except ConnectorError as exc:
        return ConnectorStatus(connector, exc.state, str(exc))
    except Exception as exc:
        return ConnectorStatus(connector, "unavailable", type(exc).__name__)


async def probe_all() -> list[ConnectorStatus]:
    names = connector_names()
    results = await asyncio.gather(*(probe(n) for n in names))
    return list(results)
