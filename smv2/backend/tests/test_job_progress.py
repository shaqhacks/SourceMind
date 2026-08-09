from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

from app.db.engine import get_session
from app.db.models import Job, ensure_utc, utcnow
from app.jobs import registry
from app.jobs.error_envelope import decode_job_error
from app.jobs.llm_job_control import completion_options_for_job
from app.jobs.worker import execute_job, job_progress
from app.llm.structured_output import InvalidModelOutputError
from app.llm.completion_control import CompletionProgress


def test_job_progress_updates_progress_and_extends_lease(client):
    session = get_session()
    try:
        job = Job(type="noop", status="running")
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    session = get_session()
    try:
        job_progress(session, job_id, stage="parsing", pct=42, message="halfway there")
    finally:
        session.close()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.progress == {"stage": "parsing", "pct": 42, "message": "halfway there"}
        assert job.lease_until is not None
    finally:
        session.close()


def test_job_progress_accepts_nullable_pct_and_timing(client):
    session = get_session()
    try:
        job = Job(type="noop", status="running")
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    session = get_session()
    try:
        job_progress(
            session,
            job_id,
            stage="thinking",
            pct=None,
            message="Thinking",
            elapsed_seconds=12,
            last_activity_seconds=3,
        )
    finally:
        session.close()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.progress == {
            "stage": "thinking",
            "pct": None,
            "message": "Thinking",
            "elapsed_seconds": 12,
            "last_activity_seconds": 3,
        }
    finally:
        session.close()


def test_job_progress_is_noop_for_missing_job(client):
    session = get_session()
    try:
        # Must not raise even if the job vanished (e.g. deleted concurrently).
        job_progress(session, "does-not-exist", stage="x", pct=0, message="")
    finally:
        session.close()


def test_job_completion_control_throttles_and_renews_lease(client, monkeypatch):
    session = get_session()
    try:
        job = Job(type="generate_cards", status="running", lease_until=utcnow() - timedelta(seconds=1))
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    from app.jobs import worker as worker_module

    writes = []
    real_job_progress = worker_module.job_progress

    def counting_job_progress(*args, **kwargs):
        writes.append((args, kwargs))
        return real_job_progress(*args, **kwargs)

    monkeypatch.setattr(worker_module, "job_progress", counting_job_progress)

    options = completion_options_for_job(job_id, artifact="flashcards")
    options.progress(CompletionProgress("thinking", 65.0, 0.0))
    options.progress(CompletionProgress("thinking", 66.0, 1.0))
    options.progress(CompletionProgress("generating", 67.0, 2.0))

    assert len(writes) == 2

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.progress == {
            "stage": "generating",
            "pct": None,
            "message": "Generating flashcards · 1m 07s",
            "elapsed_seconds": 67,
            "last_activity_seconds": 2,
        }
        assert job.lease_until is not None
        assert ensure_utc(job.lease_until) > utcnow()
    finally:
        session.close()


def test_job_completion_control_keeps_private_provider_material_out_of_progress_and_logs(
    client, caplog
):
    session = get_session()
    try:
        job = Job(type="generate_lesson", status="running")
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    private_reasoning = "PRIVATE_REASONING_SENTINEL_do_not_log"
    caplog.set_level(logging.INFO)
    options = completion_options_for_job(
        job_id,
        artifact="lesson",
        response_schema={"description": private_reasoning},
    )

    options.progress(CompletionProgress("thinking", 5.4, 0.2))

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert private_reasoning not in json.dumps(job.progress)
        assert private_reasoning not in caplog.text
    finally:
        session.close()


def test_job_completion_control_cancel_reads_committed_state(client, monkeypatch):
    session = get_session()
    try:
        job = Job(type="generate_lesson", status="running")
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    options = completion_options_for_job(job_id, artifact="lesson")

    session = get_session()
    try:
        job = session.get(Job, job_id)
        job.cancel_requested_at = utcnow()
        assert options.is_cancelled() is False
        session.commit()
    finally:
        session.close()

    assert options.is_cancelled() is True

    from app.services import jobs_service

    def raise_on_cancel_read(_job_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(jobs_service, "is_cancel_requested", raise_on_cancel_read)
    assert options.is_cancelled() is True


def test_execute_job_invalid_model_output_uses_safe_error_detail(client, monkeypatch):
    def invalid_model_handler(_session, _job):
        raise InvalidModelOutputError(
            ValueError("RAW_MODEL_SENTINEL parser text {\"secret\": true}")
        )

    monkeypatch.setitem(registry.JOB_HANDLERS, "invalid_model_test", invalid_model_handler)
    session = get_session()
    try:
        job = Job(type="invalid_model_test", status="running")
        session.add(job)
        session.commit()
        job_id = job.id
        execute_job(session, job)
    finally:
        session.close()

    session = get_session()
    try:
        stored = session.get(Job, job_id)
        message, detail = decode_job_error(stored.error)
    finally:
        session.close()

    assert stored.status == "failed"
    assert message == "The model returned an invalid question format."
    assert detail == {
        "code": "invalid_model_output",
        "message": "The model returned an invalid question format.",
        "failure_category": "structured_output_invalid",
    }
    assert "RAW_MODEL_SENTINEL" not in stored.error


def test_structured_generation_provider_calls_check_spend_cap_immediately_before():
    backend_root = Path(__file__).resolve().parents[1]
    relative_paths = [
        "app/pipeline/cards_generation.py",
        "app/pipeline/quiz_generation.py",
        "app/pipeline/practice_extraction.py",
        "app/pipeline/concept_extraction.py",
        "app/pipeline/concept_practice_generation.py",
    ]

    violations = []
    for relative_path in relative_paths:
        lines = (backend_root / relative_path).read_text().splitlines()
        for index, line in enumerate(lines):
            if "provider.complete(" not in line:
                continue
            previous = next(
                (
                    candidate.strip()
                    for candidate in reversed(lines[:index])
                    if candidate.strip()
                ),
                "",
            )
            if not previous.startswith("ensure_spend_cap("):
                violations.append(f"{relative_path}:{index + 1}")

    assert violations == []
