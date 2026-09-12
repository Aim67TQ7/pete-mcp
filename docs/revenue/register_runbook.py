"""Index owner-provided runbook through existing intake; use existing grants only."""
import asyncio, hashlib, json
from pathlib import Path
from uuid import UUID
from gateway import auth, db, policy, console_store

async def main():
    p=await db.pool()
    row=await p.fetchrow("select id,name from gateway.clients where name='robert-operator' and status='active'")
    if row is None: raise RuntimeError('Existing operator unavailable')
    grants=await p.fetch('select * from gateway.grants where client_id=$1',row['id'])
    actor=auth.Actor(str(row['id']),row['name'],{g['project']:dict(g) for g in grants})
    text=Path('/tmp/pete-revenue-gp3.md').read_text()
    assert hashlib.sha256(text.encode()).hexdigest()=='d208e364744760548fd1a367dae2d16b775c5092d4aea6c0f02e25eb0707fff5'
    policy.check_grant(actor,'platform','memory:write')
    await policy.authorize(actor,'platform','memory:write')
    result=await console_store.intake(actor,'PETE-sustainable-revenue-v1.0.0.md',text,project='platform')
    await policy.audit(actor,'runbook_install','platform','memory:write',True,{'source':'owner supplied runbook','runbook_sha256':result['sha256'],'runbook_version':'1.0.0','note':'Reference indexed; no project permission or schedule created.'})
    # Existing read-only source review handler; stable ID deduplicates retries.
    job=await console_store.message(actor,'Review uploaded knowledge','12273d06-57a5-4570-9696-29d6888b40b0',project='platform')
    print(json.dumps({'document':result,'review':job},default=str,indent=2))
    await db.close()
asyncio.run(main())
