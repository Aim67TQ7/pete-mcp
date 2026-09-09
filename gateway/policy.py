"""Policy engine: every invocation is checked for project x actor x action,
budget, and idempotency — and effects are checked again at execution time by
the worker. Memory never grants authority; only gateway.grants does."""
import json
from dataclasses import dataclass

from . import db
from .auth import Actor
from .config import PROJECTS


class PolicyDenied(Exception):
    pass


@dataclass
class Decision:
    grant_id: str
    project: str
    action: str


def scope_allows(scopes: list[str], action: str) -> bool:
    """Match an action like 'connector:github:read' against granted scopes,
    supporting trailing wildcards ('connector:*', 'memory:*', '*')."""
    for s in scopes:
        if s == "*" or s == action:
            return True
        if s.endswith(":*") and action.startswith(s[:-1]):
            return True
    return False


def check_grant(actor: Actor, project: str, action: str) -> dict:
    """Pure check: project validity, grant existence, scope match."""
    if project not in PROJECTS:
        raise PolicyDenied(f"unknown project '{project}'")
    grant = actor.grants.get(project) or actor.grants.get("platform")
    if grant is None:
        raise PolicyDenied(f"client '{actor.name}' has no grant for project '{project}'")
    if not scope_allows(list(grant["scopes"]), action):
        raise PolicyDenied(f"scope '{action}' not granted for project '{project}'")
    return grant


async def authorize(
    actor: Actor, project: str, action: str, *, cost_cents: int = 0
) -> Decision:
    """Full check including budget counters. Raises PolicyDenied."""
    grant = check_grant(actor, project, action)
    p = await db.pool()
    row = await p.fetchrow(
        """
        insert into gateway.budget_usage (grant_id, usage_date, actions, spend_cents)
        values ($1, current_date, 1, $2)
        on conflict (grant_id, usage_date)
        do update set actions = gateway.budget_usage.actions + 1,
                      spend_cents = gateway.budget_usage.spend_cents + $2
        returning actions, spend_cents
        """,
        grant["id"],
        cost_cents,
    )
    if row["actions"] > grant["daily_action_cap"]:
        raise PolicyDenied("daily action cap exceeded")
    if grant["daily_spend_cap_cents"] and row["spend_cents"] > grant["daily_spend_cap_cents"]:
        raise PolicyDenied("daily spend cap exceeded")
    return Decision(grant_id=str(grant["id"]), project=project, action=action)


async def claim_effect(actor: Actor, project: str, action: str, effect_key: str) -> dict | None:
    """Idempotency: returns the prior result if this effect already ran,
    else records the claim and returns None (caller proceeds)."""
    p = await db.pool()
    existing = await p.fetchrow(
        "select result_json from gateway.effects where effect_key=$1", effect_key
    )
    if existing is not None:
        return {"duplicate": True, "result": json.loads(existing["result_json"] or "null")}
    await p.execute(
        "insert into gateway.effects (effect_key, client_id, project, action) "
        "values ($1,$2,$3,$4) on conflict do nothing",
        effect_key, actor.client_id, project, action,
    )
    return None


async def record_effect_result(effect_key: str, result: dict) -> None:
    p = await db.pool()
    await p.execute(
        "update gateway.effects set result_json=$2 where effect_key=$1",
        effect_key, json.dumps(result),
    )


async def audit(actor: Actor | None, tool: str, project: str | None,
                action: str | None, allowed: bool, detail: dict | None = None) -> None:
    try:
        p = await db.pool()
        await p.execute(
            "insert into gateway.audit_log (client_name, project, tool, action, allowed, detail_json) "
            "values ($1,$2,$3,$4,$5,$6)",
            actor.name if actor else None, project, tool, action, allowed,
            json.dumps(detail or {}),
        )
    except Exception:
        pass  # audit is best-effort; never blocks the request path
