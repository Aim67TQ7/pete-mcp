"""Shared cross-client memory: facts vs decisions vs suggestions, provenance
mandatory, optimistic version checks. Clients retrieve explicitly — nothing
synchronizes silently, and memory never grants authority."""
import json

from . import db


async def search(project: str, query: str, kind: str | None = None, limit: int = 20) -> list[dict]:
    p = await db.pool()
    limit = min(limit, 100)
    conditions = ["project = $1", "status = 'active'"]
    args: list = [project]
    if query.strip():
        args.append(query)
        conditions.append(f"search @@ plainto_tsquery('english', ${len(args)})")
    if kind:
        args.append(kind)
        conditions.append(f"kind = ${len(args)}")
    args.append(limit)
    rows = await p.fetch(
        f"""select id, project, kind, content, evidence_url, author, confidence,
                   version, tags, created_at, updated_at
            from gateway.memories where {' and '.join(conditions)}
            order by created_at desc limit ${len(args)}""",
        *args,
    )
    return [
        {**dict(r), "id": str(r["id"]),
         "created_at": r["created_at"].isoformat(),
         "updated_at": r["updated_at"].isoformat()}
        for r in rows
    ]


async def record(project: str, kind: str, content: str, author: str, *,
                 evidence_url: str | None = None, confidence: float = 0.5,
                 tags: list[str] | None = None) -> dict:
    p = await db.pool()
    row = await p.fetchrow(
        """insert into gateway.memories (project, kind, content, evidence_url, author, confidence, tags)
           values ($1,$2,$3,$4,$5,$6,$7) returning id, version, created_at""",
        project, kind, content, evidence_url, author, confidence, tags or [],
    )
    return {"id": str(row["id"]), "version": row["version"],
            "created_at": row["created_at"].isoformat()}


async def supersede(memory_id: str, expected_version: int, new_content: str,
                    author: str, *, evidence_url: str | None = None,
                    confidence: float = 0.5) -> dict:
    """Optimistic concurrency: fails if another client edited in the meantime."""
    p = await db.pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            old = await conn.fetchrow(
                "select project, kind, version from gateway.memories "
                "where id=$1::uuid and status='active' for update", memory_id)
            if old is None:
                raise ValueError("memory not found or not active")
            if old["version"] != expected_version:
                raise ValueError(
                    f"version conflict: expected {expected_version}, current {old['version']}")
            new = await conn.fetchrow(
                """insert into gateway.memories
                   (project, kind, content, evidence_url, author, confidence, version)
                   values ($1,$2,$3,$4,$5,$6,$7) returning id""",
                old["project"], old["kind"], new_content, evidence_url, author,
                confidence, old["version"] + 1)
            await conn.execute(
                "update gateway.memories set status='superseded', superseded_by=$2, "
                "updated_at=now() where id=$1::uuid", memory_id, new["id"])
    return {"id": str(new["id"]), "version": old["version"] + 1, "superseded": memory_id}
