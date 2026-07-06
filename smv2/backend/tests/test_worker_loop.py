from __future__ import annotations

import asyncio
from datetime import timedelta

from app.db.engine import get_session
from app.db.models import Job, utcnow
from app.jobs import worker


def test_worker_loop_periodically_reconciles_expired_leases(client, monkeypatch):
    """A fast restart within a job's lease window used to wedge that job
    'running' forever — reconcile_interrupted_jobs() only ran once, at
    startup, so the claim SQL (status='queued' only) could never see it
    again. worker_loop() now re-runs the reconciler periodically while the
    process is alive, recovering the job with no restart at all.
    """
    session = get_session()
    try:
        job = Job(type="noop", status="running", lease_until=utcnow() - timedelta(seconds=5))
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    monkeypatch.setattr(worker, "RECONCILE_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(worker, "POLL_INTERVAL_SECONDS", 0.01)

    async def _run_briefly() -> None:
        task = asyncio.create_task(worker.worker_loop())
        await asyncio.sleep(0.4)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run_briefly())

    session = get_session()
    try:
        recovered = session.get(Job, job_id)
        # default_on_orphan requeues (status='queued', lease cleared) since
        # attempts < MAX_ORPHAN_ATTEMPTS; the loop may then ALSO claim and
        # run it (a noop succeeds instantly) before the 0.4s window closes.
        # Either outcome proves the reconciler fired without a restart —
        # what must NOT happen is it staying 'running' with its original,
        # already-expired lease untouched.
        assert recovered.status in ("queued", "succeeded")
        if recovered.status == "queued":
            assert recovered.lease_until is None
    finally:
        session.close()
