from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.engine import get_session
from app.db.models import Job, Section
from app.jobs.registry import MAX_ORPHAN_ATTEMPTS
from app.jobs.worker import reconcile_interrupted_jobs
from conftest import _first_section_id


def _insert_orphaned_generate_lesson_job(section_id: str, attempts: int) -> str:
    session = get_session()
    try:
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        job = Job(
            type="generate_lesson",
            status="running",
            lease_until=past,
            attempts=attempts,
            payload={"section_id": section_id},
        )
        session.add(job)
        session.commit()
        return job.id
    finally:
        session.close()


def test_orphaned_generate_lesson_under_attempt_limit_requeues_and_resets_status(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    session = get_session()
    try:
        section = session.get(Section, section_id)
        section.lesson_status = "generating"
        session.commit()
    finally:
        session.close()

    job_id = _insert_orphaned_generate_lesson_job(section_id, attempts=1)

    reconcile_interrupted_jobs()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.status == "queued"
        section = session.get(Section, section_id)
        assert section.lesson_status == "queued"
    finally:
        session.close()


def test_orphaned_generate_lesson_exhausted_fails_and_marks_lesson_failed(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    session = get_session()
    try:
        section = session.get(Section, section_id)
        section.lesson_status = "generating"
        session.commit()
    finally:
        session.close()

    job_id = _insert_orphaned_generate_lesson_job(section_id, attempts=MAX_ORPHAN_ATTEMPTS)

    reconcile_interrupted_jobs()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.status == "failed"
        section = session.get(Section, section_id)
        assert section.lesson_status == "failed"
    finally:
        session.close()
