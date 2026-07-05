from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Chunk
from app.llm.provider import NotSupportedError
from app.services import jobs_service


def _chunk_count(course_id: str, embedded: bool | None = None) -> int:
    session = get_session()
    try:
        q = session.query(Chunk).filter(Chunk.course_id == course_id)
        if embedded is True:
            q = q.filter(Chunk.embedding.isnot(None))
        elif embedded is False:
            q = q.filter(Chunk.embedding.is_(None))
        return q.count()
    finally:
        session.close()


def test_embed_course_embeds_all_null_chunks(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    total = _chunk_count(course_id)
    assert total > 0
    assert _chunk_count(course_id, embedded=False) == total

    from app.jobs.worker import run_due_jobs_once

    jobs_service.create_job("embed_course", {"course_id": course_id})
    assert run_due_jobs_once() is True

    assert _chunk_count(course_id, embedded=True) == total
    assert _chunk_count(course_id, embedded=False) == 0
    assert stub_provider.embed_call_count == 1


def test_embed_course_per_item_isolation_leaves_failed_ones_null(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    total = _chunk_count(course_id)
    assert total > 1

    # First chunk fails to embed, rest succeed.
    stub_provider.embed_responses = [None] + [[0.1, 0.2, 0.3]] * (total - 1)

    from app.jobs.worker import run_due_jobs_once

    jobs_service.create_job("embed_course", {"course_id": course_id})
    assert run_due_jobs_once() is True

    assert _chunk_count(course_id, embedded=True) == total - 1
    assert _chunk_count(course_id, embedded=False) == 1


def test_embed_course_no_op_when_no_null_chunks(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    from app.jobs.worker import run_due_jobs_once

    jobs_service.create_job("embed_course", {"course_id": course_id})
    assert run_due_jobs_once() is True
    assert stub_provider.embed_call_count == 1

    # Second run: nothing left to embed.
    jobs_service.create_job("embed_course", {"course_id": course_id})
    assert run_due_jobs_once() is True
    assert stub_provider.embed_call_count == 1  # not called again


def test_embed_course_provider_not_supported_leaves_all_null(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    total = _chunk_count(course_id)

    stub_provider.embed_exception = NotSupportedError("Anthropic has no embeddings API")

    from app.jobs.worker import run_due_jobs_once

    resp_job_id = jobs_service.create_job("embed_course", {"course_id": course_id}).id
    assert run_due_jobs_once() is True

    from app.db.models import Job

    session = get_session()
    try:
        job = session.get(Job, resp_job_id)
        assert job.status == "succeeded"  # graceful degrade, not a failed job
        assert job.result["skipped"] == total
    finally:
        session.close()

    assert _chunk_count(course_id, embedded=False) == total
