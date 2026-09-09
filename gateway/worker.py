"""PETE worker: executes queued jobs independently of open chats.
Registered handlers only; each records a verification observation (RULE_4) or
the job lands as unverified/error, never fake success."""
import asyncio
import logging
import signal

from . import db, jobs, memory, reports
from .connectors import engine

log = logging.getLogger("pete.worker")

POLL_SECONDS = 5


async def _handle_noop(job: dict) -> tuple[dict, dict]:
    return {"echo": job["args"]}, {"source_of_truth": "n/a", "observation": "noop completed"}


async def _handle_probe_connectors(job: dict) -> tuple[dict, dict]:
    statuses = await engine.probe_all()
    result = {s.name: s.state for s in statuses}
    return ({"connectors": result},
            {"source_of_truth": "live provider probes",
             "observation": f"{sum(1 for v in result.values() if v == 'connected')}"
                            f"/{len(result)} connected"})


async def _handle_build_report(job: dict) -> tuple[dict, dict]:
    body = await reports.build(job["args"].get("scope", "consolidated"))
    return ({"report_date": body["date"], "blockers": len(body["blockers"])},
            {"source_of_truth": "gateway.reports row",
             "observation": f"report stored for {body['date']}"})


async def _handle_memory_digest(job: dict) -> tuple[dict, dict]:
    project = job["args"].get("project", "platform")
    entries = await memory.search(project, "", limit=50)
    facts = sum(1 for e in entries if e["kind"] == "fact")
    decisions = sum(1 for e in entries if e["kind"] == "decision")
    content = (f"Digest: {len(entries)} active entries "
               f"({facts} facts, {decisions} decisions) as of this run.")
    rec = await memory.record(project, "suggestion", content, "pete-worker",
                              confidence=0.9, tags=["digest"])
    return ({"digest_id": rec["id"]},
            {"source_of_truth": "gateway.memories",
             "observation": f"digest row {rec['id']} written"})


HANDLERS = {
    "noop": _handle_noop,
    "probe_connectors": _handle_probe_connectors,
    "build_report": _handle_build_report,
    "memory_digest": _handle_memory_digest,
}


async def run_one(job: dict) -> None:
    handler = HANDLERS.get(job["job_type"])
    if handler is None:
        await jobs.finish(job["id"], "error", error=f"no handler for {job['job_type']}")
        return
    try:
        result, verification = await asyncio.wait_for(handler(job), timeout=240)
        await jobs.finish(job["id"], "success", result=result, verification=verification)
        log.info("job %s (%s) succeeded", job["id"], job["job_type"])
    except asyncio.TimeoutError:
        status = "timeout" if job["attempts"] >= job["max_attempts"] else "pending"
        await jobs.finish(job["id"], status, error="handler timeout")
    except Exception as exc:  # bounded retries via attempts/max_attempts
        status = "error" if job["attempts"] >= job["max_attempts"] else "pending"
        await jobs.finish(job["id"], status, error=f"{type(exc).__name__}: {exc}")
        log.warning("job %s failed (attempt %s/%s): %s",
                    job["id"], job["attempts"], job["max_attempts"], exc)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("PETE worker started")
    while not stop.is_set():
        job = await jobs.claim_next("pete-worker")
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
            continue
        await run_one(job)
    await db.close()
    log.info("PETE worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
