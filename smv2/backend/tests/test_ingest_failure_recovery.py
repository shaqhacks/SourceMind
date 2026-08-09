from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_mid_run_exception_marks_job_failed_and_course_ingest_failed(client, ingest_course, monkeypatch):
    """Regression: an unhandled exception partway through _run_ingest must
    not leave course.status stuck on 'ingesting' forever — it's a terminal
    job failure with no restart story otherwise.
    """
    import app.pipeline.ingest as ingest_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated mid-ingest failure")

    monkeypatch.setattr(ingest_module, "chunk_pages", _boom)

    course_id, _, ingest_resp, claimed = ingest_course("with_bookmarks.pdf")
    assert claimed is True  # the job was claimed and executed, even though it failed

    job_id = ingest_resp.json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "simulated mid-ingest failure" in job["error"]

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ingest_failed"


def test_orphan_exhausted_ingest_job_marks_course_ingest_failed(client):
    """Regression: when the reconciler gives up on an orphaned 'ingest' job
    for good (attempts exhausted -> job failed), course.status must follow
    suit rather than staying on a stale 'ingesting'.
    """
    from app.db.engine import get_session
    from app.db.models import Job
    from app.jobs.registry import MAX_ORPHAN_ATTEMPTS
    from app.jobs.worker import reconcile_interrupted_jobs
    from app.services import courses_service

    resp = client.post("/api/courses", json={"title": "Orphaned Ingest Course"})
    course_id = resp.json()["id"]
    courses_service.set_course_status(course_id, "ingesting")

    session = get_session()
    try:
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        job = Job(
            type="ingest",
            status="running",
            lease_until=past,
            attempts=MAX_ORPHAN_ATTEMPTS,
            payload={"course_id": course_id},
        )
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    reconcile_interrupted_jobs()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.status == "failed"
    finally:
        session.close()

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ingest_failed"
