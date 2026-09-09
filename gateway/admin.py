"""Operator CLI: client keys, grants, revocation. Run on the gateway host only.
The raw key prints exactly once at creation and is never stored or logged.

  python -m gateway.admin create-client claude
  python -m gateway.admin grant claude copackers 'memory:*,jobs:*,reports:read,connector:*:read'
  python -m gateway.admin revoke chatgpt
  python -m gateway.admin list
"""
import asyncio
import sys

from . import auth, db


async def create_client(name: str) -> None:
    key = auth.generate_key()
    p = await db.pool()
    await p.execute(
        "insert into gateway.clients (name, key_hash) values ($1,$2)",
        name, auth.hash_key(key))
    print(f"client '{name}' created")
    print(f"bearer key (shown once, store in the client's connector config): {key}")


async def grant(name: str, project: str, scopes_csv: str,
                action_cap: str = "500", spend_cap_cents: str = "0") -> None:
    scopes = [s.strip() for s in scopes_csv.split(",") if s.strip()]
    p = await db.pool()
    client_id = await p.fetchval("select id from gateway.clients where name=$1", name)
    if client_id is None:
        sys.exit(f"no client named '{name}'")
    await p.execute(
        """insert into gateway.grants (client_id, project, scopes, daily_action_cap, daily_spend_cap_cents)
           values ($1,$2,$3,$4,$5)
           on conflict (client_id, project)
           do update set scopes=$3, daily_action_cap=$4, daily_spend_cap_cents=$5""",
        client_id, project, scopes, int(action_cap), int(spend_cap_cents))
    print(f"granted {name} on {project}: {scopes}")


async def revoke(name: str) -> None:
    p = await db.pool()
    n = await p.execute(
        "update gateway.clients set status='revoked' where name=$1", name)
    print(f"revoked '{name}' ({n})")


async def list_clients() -> None:
    p = await db.pool()
    rows = await p.fetch(
        """select c.name, c.status, c.last_seen_at,
                  coalesce(array_agg(g.project) filter (where g.project is not null), '{}') as projects
           from gateway.clients c left join gateway.grants g on g.client_id=c.id
           group by c.id order by c.name""")
    for r in rows:
        print(f"{r['name']:<14} {r['status']:<8} projects={list(r['projects'])} "
              f"last_seen={r['last_seen_at']}")


COMMANDS = {"create-client": create_client, "grant": grant,
            "revoke": revoke, "list": list_clients}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: python -m gateway.admin [{'|'.join(COMMANDS)}] args...")
    asyncio.run(COMMANDS[sys.argv[1]](*sys.argv[2:]))


if __name__ == "__main__":
    main()
