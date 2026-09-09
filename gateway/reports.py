"""Consolidated reporting: per-project evidence (memory decisions/facts, job
outcomes, connector readiness), blockers, and exactly five next actions.
Drafts vs sends vs deliveries stay separate — only provider-evidenced effects
count as real."""
import json
from datetime import date

from . import db, jobs
from .connectors import engine

PROJECT_SCOPES = ["copackers", "bypete", "offduty"]


async def build(scope: str = "consolidated") -> dict:
    p = await db.pool()
    statuses = await engine.probe_all()
    body: dict = {
        "scope": scope,
        "date": date.today().isoformat(),
        "connectors": {
            s.name: {"state": s.state, **({"instances": s.instances} if s.instances else {})}
            for s in statuses
        },
        "projects": {},
        "blockers": [],
        "next_actions": [],
    }
    for proj in PROJECT_SCOPES:
        mem = await p.fetch(
            """select kind, count(*) as n from gateway.memories
               where project=$1 and status='active' group by kind""", proj)
        job_rows = await p.fetch(
            """select status, count(*) as n from gateway.jobs
               where project=$1 and created_at > now() - interval '7 days'
               group by status""", proj)
        body["projects"][proj] = {
            "memory": {r["kind"]: r["n"] for r in mem},
            "jobs_7d": {r["status"]: r["n"] for r in job_rows},
        }
    disconnected = [n for n, s in body["connectors"].items() if s["state"] != "connected"]
    if disconnected:
        body["blockers"].append(
            f"Connectors not ready: {', '.join(disconnected)} — connect or provision credentials")
    depth = await jobs.queue_depth()
    if depth.get("error", 0):
        body["blockers"].append(f"{depth['error']} job(s) in error state need review")
    body["next_actions"] = _next_actions(body)[:5]
    await p.execute(
        """insert into gateway.reports (report_date, scope, body_json)
           values (current_date, $1, $2)
           on conflict (report_date, scope) do update set body_json=$2, created_at=now()""",
        scope, json.dumps(body))
    return body


def _next_actions(body: dict) -> list[str]:
    actions: list[str] = []
    for name, st in body["connectors"].items():
        if st["state"] == "reauth_required":
            actions.append(f"Reauthorize {name} credential on the gateway host")
        elif st["state"] == "unconfigured":
            actions.append(f"Provision {name} env credentials in the server-side .env")
    for proj, data in body["projects"].items():
        if not data["memory"]:
            actions.append(f"Seed {proj} memory with current facts and open decisions")
    actions.append("Review latest consolidated report and clear blockers")
    return actions


async def get(report_date: str | None = None, scope: str = "consolidated") -> dict | None:
    p = await db.pool()
    if report_date:
        row = await p.fetchrow(
            "select body_json, created_at from gateway.reports where report_date=$1::date and scope=$2",
            report_date, scope)
    else:
        row = await p.fetchrow(
            "select body_json, created_at from gateway.reports where scope=$1 "
            "order by report_date desc limit 1", scope)
    if row is None:
        return None
    body = json.loads(row["body_json"])
    body["generated_at"] = row["created_at"].isoformat()
    return body
