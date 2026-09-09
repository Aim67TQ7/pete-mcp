import pytest

from gateway.connectors import ConnectorError
from gateway.connectors import engine


def test_registry_loads_all_connectors():
    names = engine.connector_names()
    for expected in ["github", "hubspot", "stripe", "netlify", "slack", "heygen",
                     "make", "cloudflare", "supabase", "epicor", "gmail", "ms365", "vps"]:
        assert expected in names


def test_unknown_connector_lists_registered():
    with pytest.raises(ConnectorError) as exc:
        engine.operation_spec("nope", "anything")
    assert "github" in str(exc.value)


def test_unknown_operation_lists_registered():
    with pytest.raises(ConnectorError) as exc:
        engine.operation_spec("github", "delete_everything")
    assert "repos_list" in str(exc.value)


def test_write_flags():
    assert engine.is_write("github", "issue_create") is True
    assert engine.is_write("github", "repos_list") is False
    assert engine.is_write("gmail", "send") is True
    assert engine.is_write("gmail", "search") is False
    assert engine.is_write("slack", "post_message") is True
    assert engine.is_write("epicor", "baq_get") is False


def test_adapter_ops_registered():
    for connector, op in [("supabase", "select"), ("epicor", "baq_get"),
                          ("gmail", "profile"), ("vps", "fleet"), ("ms365", "organization")]:
        spec, opspec = engine.operation_spec(connector, op)
        assert spec["kind"] == "adapter"


@pytest.mark.asyncio
async def test_unconfigured_probe_is_honest(monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    status = await engine.probe("stripe")
    assert status.state == "unconfigured"


@pytest.mark.asyncio
async def test_unregistered_param_rejected(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    with pytest.raises(ConnectorError):
        await engine.run("github", "repos_list", {"evil": "1; rm -rf"})
