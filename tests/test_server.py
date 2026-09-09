import httpx
import pytest

from gateway.server import app


@pytest.mark.asyncio
async def test_healthz_public():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_protected_resource_metadata_public():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    assert resp.json()["resource"].endswith("/mcp")


@pytest.mark.asyncio
async def test_mcp_requires_bearer():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp", json={})
    assert resp.status_code == 401
    assert "resource_metadata" in resp.headers.get("www-authenticate", "")


@pytest.mark.asyncio
async def test_mcp_rejects_malformed_key():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong-format"})
    assert resp.status_code == 401
