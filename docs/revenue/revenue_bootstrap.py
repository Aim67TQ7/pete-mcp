"""Read current PETE deployment metadata; preserve all grants and runtime settings."""
import asyncio, hashlib, json, os, re
from pathlib import Path
from datetime import datetime, timezone
from gateway import db, gp3

async def main():
    pool=await db.pool()
    raw=Path('/tmp/pete-revenue-gp3.md').read_bytes()
    text=raw.decode('utf-8')
    rules=[json.loads(s) for s in re.findall(r'```json\s*\n(.*?)\n```',text,re.S)]
    anchors=re.findall(r'<a id="([^"]+)"></a>',text)
    assert rules[0]['rule']==0 and rules[1]['rule']==1
    assert all(s['id'] in anchors for s in rules[1]['sections'])
    result={'observed_at':datetime.now(timezone.utc).isoformat(),'runbook_sha256':hashlib.sha256(raw).hexdigest(),'runbook_version':rules[0]['version'],'document_validation':'passed','source_parser':str(Path(gp3.__file__))}
    try: gp3.parse(text,strict=True); result['native_parser']='compatible'
    except ValueError as exc: result['native_parser']='adapter required: '+str(exc)
    result['grants']=[dict(r) for r in await pool.fetch("select c.name,g.project,g.scopes,g.daily_action_cap,g.daily_spend_cap_cents from gateway.clients c join gateway.grants g on g.client_id=c.id where c.status='active' and g.project in ('copackers','platform') order by c.name,g.project")]
    result['recent_jobs']=[dict(r) for r in await pool.fetch("select id,project,job_type,status,submitted_by from gateway.jobs order by created_at desc limit 5")]
    result['revenue_assignments']=[dict(r) for r in await pool.fetch("select id,actor,project,objective,state,progress from gateway.assignments where project='copackers' or objective ilike '%revenue%' or objective ilike '%copackers%' order by created_at desc limit 6")]
    result['credential_presence']={k:bool(os.environ.get(k)) for k in ['GMAIL_PETE_CLIENT_ID','GMAIL_PETE_CLIENT_SECRET','GMAIL_PETE_REFRESH_TOKEN','OPENROUTER_API_KEY','STRIPE_SECRET_KEY','SUPABASE_PZLO_URL','SUPABASE_PZLO_SERVICE_ROLE_KEY']}
    result['runtime_control']=[dict(r) for r in await pool.fetch('select * from gateway.runtime_control')]
    from gateway.core_config import projects
    result['execution_projects']=list(projects())
    print(json.dumps(result,default=str,indent=2))
    await db.close()
asyncio.run(main())
