import pytest

from gateway.auth import Actor
from gateway.policy import PolicyDenied, check_grant, scope_allows


def make_actor(scopes, project="copackers"):
    return Actor(client_id="c1", name="claude", grants={
        project: {"id": "g1", "project": project, "scopes": scopes,
                  "daily_action_cap": 500, "daily_spend_cap_cents": 0}})


def test_scope_exact_and_wildcards():
    assert scope_allows(["memory:read"], "memory:read")
    assert scope_allows(["memory:*"], "memory:write")
    assert scope_allows(["connector:*"], "connector:github:read")
    assert scope_allows(["*"], "anything:at:all")
    assert not scope_allows(["memory:read"], "memory:write")
    assert not scope_allows(["connector:github:read"], "connector:github:write")
    assert not scope_allows([], "memory:read")


def test_check_grant_allows_matching_scope():
    actor = make_actor(["memory:*", "jobs:submit"])
    grant = check_grant(actor, "copackers", "memory:write")
    assert grant["id"] == "g1"


def test_check_grant_denies_unknown_project():
    actor = make_actor(["*"])
    with pytest.raises(PolicyDenied):
        check_grant(actor, "not-a-project", "memory:read")


def test_check_grant_denies_missing_grant():
    actor = make_actor(["*"], project="bypete")
    with pytest.raises(PolicyDenied):
        check_grant(actor, "offduty", "memory:read")


def test_check_grant_denies_missing_scope():
    actor = make_actor(["memory:read"])
    with pytest.raises(PolicyDenied):
        check_grant(actor, "copackers", "connector:gmail:send")


def test_platform_grant_covers_other_projects():
    actor = Actor(client_id="c1", name="claude", grants={
        "platform": {"id": "gp", "project": "platform", "scopes": ["reports:read"],
                     "daily_action_cap": 500, "daily_spend_cap_cents": 0}})
    assert check_grant(actor, "bypete", "reports:read")["id"] == "gp"
