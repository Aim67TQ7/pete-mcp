"""Durable job queue: registered types only, leases, bounded retries,
effect-key dedup across clients. RULE_4 statuses; success requires a
verification observation against a source of truth."""
import json

from . import db

# Registered job types with bounded argument keys. No arbitrary shell entrypoint.
JOB_TYPES: dict[str, dict] = {
    "noop": {"args": [], "description": "Smoke-test job"},
    "probe_connectors": {"args": [], "description": "Refresh connector readiness states"},
    "build_report": {"args": ["scope"], "description": "Build the consolidated evening report"},
    "memory_digest": {"args": ["project"], "description": "Summarize recent memory into a digest entry"},
}

LEASE_SECONDS = 300


async def submit(project: str, job_type: str, args: dict, submitted_by: str,
                 effect_key: str | None = None) -> dict:
    if job_type not in JOB_TYPES:
        raise ValueError(f"unregistered job type '{job_type}'. Registered: {', '.join(sorted(JOB_TYPES))}")
    allowed = set(JOB_TYPES[job_type]["args"])
    extra = set(args) - allowed
    if extra:
        raise ValueError(f"unregistered args {sorted(extra)} for job type '{job_type}'")
    p = await db.pool()
    if effect_key:
        existing = await p.fetchrow(
            "select id, status from gateway.jobs where effect_key=$1", effect_key)
        if existing:
            return {"job_id": str(existing["id"]), "status": existing["status"], "duplicate": True}
    row = await p.fetchrow(
        """insert into gateway.jobs (project, job_type, args_json, submitted_by, effect_key)
           values ($1,$2,$3,$4,$5) returning id, status""",
        project, job_type, json.dumps(args), submitted_by, effect_key)
    return {"job_id": str(row["id"]), "status": row["status"], "duplicate": False}


async def get(job_id: str) -> dict | None:
    p = await db.pool()
    row = await p.fetchrow(
        """select id, project, job_type, status, attempts, max_attempts, submitted_by,
                  result_json, verification_json, error, created_at, updated_at
           from gateway.jobs where id=$1::uuid""", job_id)
    if row is None:
        return None
    out = dict(row)
    out["id"] = str(out["id"])
    out["created_at"] = out["created_at"].isoformat()
    out["updated_at"] = out["updated_at"].isoformat()
    for k in ("result_json", "verification_json"):
        if out[k]:
            out[k] = json.loads(out[k])
    return out


async def cancel(job_id: str) -> dict:
    p = await db.pool()
    row = await p.fetchrow(
        """update gateway.jobs set status='cancelled', updated_at=now()
           where id=$1::uuid and status in ('pending','running')
           returning id, status""", job_id)
    if row is None:
        return {"job_id": job_id, "cancelled": False,
                "reason": "not found or already terminal"}
    return {"job_id": str(row["id"]), "cancelled": True}


async def claim_next(worker_id: str) -> dict | None:
    """Claim one runnable job with SKIP LOCKED + lease. Expired leases requeue."""
    p = await db.pool()
    row = await p.fetchrow(
        f"""update gateway.jobs set status='running', attempts=attempts+1,
                   lease_expires_at=now() + interval '{LEASE_SECONDS} seconds',
                   updated_at=now()
            where id = (
              select id from gateway.jobs
              where (status='pending' and attempts < max_attempts)
                 or (status='running' and lease_expires_at < now() and attempts < max_attempts)
              order by priority, created_at
              for update skip locked limit 1)
            returning id, project, job_type, args_json, attempts, max_attempts""")
    if row is None:
        return None
    return {"id": str(row["id"]), "project": row["project"], "job_type": row["job_type"],
            "args": json.loads(row["args_json"]), "attempts": row["attempts"],
            "max_attempts": row["max_attempts"]}


async def finish(job_id: str, status: str, *, result: dict | None = None,
                 verification: dict | None = None, error: str | None = None) -> None:
    if status == "success" and not verification:
        # RULE_4: success without a verification observation is 'unverified'.
        status = "unverified"
    p = await db.pool()
    await p.execute(
        """update gateway.jobs set status=$2, result_json=$3, verification_json=$4,
                  error=$5, lease_expires_at=null, updated_at=now()
           where id=$1::uuid""",
        job_id, status, json.dumps(result) if result else None,
        json.dumps(verification) if verification else None, error)


async def queue_depth() -> dict:
    p = await db.pool()
    rows = await p.fetch(
        "select status, count(*) as n from gateway.jobs group by status")
    return {r["status"]: r["n"] for r in rows}
