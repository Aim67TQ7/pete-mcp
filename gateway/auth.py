"""Per-client bearer key auth.

Keys look like pmk_<48 hex>. Only the sha256 hash is stored; each AI client
(claude, chatgpt, gemini-cli, grok, pete-qwen, ...) holds its own key and is
revocable independently. Full OAuth AS integration is staged (see docs/CLIENTS.md);
the protected-resource metadata endpoint is already served for discovery.
"""
import hashlib
import secrets
from contextvars import ContextVar
from dataclasses import dataclass, field

from . import db

_current_actor: ContextVar["Actor | None"] = ContextVar("actor", default=None)


@dataclass
class Actor:
    client_id: str
    name: str
    grants: dict[str, dict] = field(default_factory=dict)  # project -> grant row


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_key() -> str:
    return "pmk_" + secrets.token_hex(24)


def current_actor() -> Actor:
    actor = _current_actor.get()
    if actor is None:
        raise PermissionError("unauthenticated")
    return actor


def set_current_actor(actor: "Actor | None"):
    return _current_actor.set(actor)


async def authenticate(raw_key: str) -> Actor | None:
    """Resolve a bearer key to an Actor with its per-project grants, or None."""
    if not raw_key or not raw_key.startswith("pmk_"):
        return None
    kh = hash_key(raw_key)
    p = await db.pool()
    row = await p.fetchrow(
        "select id, name from gateway.clients where key_hash=$1 and status='active'", kh
    )
    if row is None:
        return None
    grants = await p.fetch(
        "select id, project, scopes, daily_action_cap, daily_spend_cap_cents "
        "from gateway.grants where client_id=$1",
        row["id"],
    )
    await p.execute("update gateway.clients set last_seen_at=now() where id=$1", row["id"])
    return Actor(
        client_id=str(row["id"]),
        name=row["name"],
        grants={g["project"]: dict(g) for g in grants},
    )
