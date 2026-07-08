from __future__ import annotations

import json
import uuid

import pytest

from app.db.engine import get_session
from app.db.models import Concept, Course, Job, PracticeExtractionRun, PracticeQuestion, Section
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from app.pipeline.practice_extraction import parse_practice_questions


def _seed_practice_run(session, *, with_answers: bool = True):
    course = Course(title="Practice Extraction Course")
    session.add(course)
    session.flush()

    practice = Section(
        id=f"practice-{uuid.uuid4()}",
        course_id=course.id,
        order_index=1,
        title="0.2 Practice - Fractions",
        body_md="1. Simplify 42/12.",
        content_hash="practice-hash",
        kind="practice",
        chapter_label="Chapter 0 : Pre-Algebra",
        page_start=3,
        page_end=4,
    )
    session.add(practice)

    answers = None
    if with_answers:
        answers = Section(
            id=f"answers-{uuid.uuid4()}",
            course_id=course.id,
            order_index=2,
            title="0.2 Answers - Fractions",
            body_md="1. 7/2.",
            content_hash="answers-hash",
            kind="answers",
            chapter_label=practice.chapter_label,
        )
        session.add(answers)
    session.flush()

    run = PracticeExtractionRun(
        course_id=course.id,
        section_id=practice.id,
        status="queued",
        input_fingerprint=f"fingerprint-{uuid.uuid4()}",
    )
    session.add(run)
    session.flush()

    job = Job(
        type="generate_practice_assessment",
        status="queued",
        payload={"course_id": course.id, "section_id": practice.id, "run_id": run.id},
    )
    session.add(job)
    session.flush()
    run.job_id = job.id
    session.commit()
    return course, practice, answers, run, job


def _valid_question_payload():
    return {
        "problem_number": "1",
        "stem_md": "Simplify $42/12$.",
        "textbook_answer_md": "$7/2$",
        "choices": ["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
        "correct_index": 0,
        "explanation_md": "$42/12 = 7/2$.",
        "concept_slug": "fractions.simplify",
        "concept_label": "Simplifying Fractions",
        "answer_source_ref": "0.2 Answers - Fractions #1",
        "confidence": 0.95,
    }


def test_parse_practice_questions_drops_unmapped_answer():
    valid = _valid_question_payload()
    unmapped = {
        **_valid_question_payload(),
        "problem_number": "2",
        "textbook_answer_md": "",
        "confidence": 0.2,
    }

    questions = parse_practice_questions(f"```json\n{json.dumps([valid, unmapped])}\n```")

    assert len(questions) == 1
    assert questions[0]["problem_number"] == "1"
    assert questions[0]["choices"][questions[0]["correct_index"]] == "$7/2$"
    assert "textbook_answer_md" not in questions[0]


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_parse_practice_questions_rejects_non_finite_confidence_constants(constant):
    payload = json.dumps(_valid_question_payload()).replace("0.95", constant)

    with pytest.raises(ValueError, match="invalid JSON constant"):
        parse_practice_questions(f"[{payload}]")


def test_parse_practice_questions_drops_confidence_above_one():
    payload = {**_valid_question_payload(), "confidence": 1.2}

    assert parse_practice_questions(json.dumps([payload])) == []


def test_practice_extraction_job_persists_ready_questions(client, stub_provider):
    session = get_session()
    try:
        course, practice, _answers, run, job = _seed_practice_run(session)
    finally:
        session.close()

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([_valid_question_payload()]),
            input_tokens=100,
            output_tokens=50,
            model="stub-model",
        )
    ]

    assert run_due_jobs_once() is True

    session = get_session()
    try:
        stored_job = session.get(Job, job.id)
        stored_run = session.get(PracticeExtractionRun, run.id)
        question = session.query(PracticeQuestion).one()
        concept = session.query(Concept).one()

        assert stored_job is not None
        assert stored_job.status == "succeeded"
        assert stored_job.result == {"question_count": 1}
        assert stored_run is not None
        assert stored_run.status == "ready"
        assert stored_run.question_count == 1
        assert stored_run.error is None
        assert question.correct_index == 0
        assert question.status == "ready"
        assert question.section_id == practice.id
        assert question.answer_source_ref == "0.2 Answers - Fractions #1"
        assert question.concept_id == concept.id
        assert concept.slug == "fractions.simplify"
    finally:
        session.close()


def test_practice_extraction_job_dedupes_duplicate_source_fingerprints(client, stub_provider):
    session = get_session()
    try:
        _course, _practice, _answers, run, job = _seed_practice_run(session)
    finally:
        session.close()

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([_valid_question_payload(), _valid_question_payload()]),
            input_tokens=100,
            output_tokens=50,
            model="stub-model",
        )
    ]

    assert run_due_jobs_once() is True

    session = get_session()
    try:
        stored_job = session.get(Job, job.id)
        stored_run = session.get(PracticeExtractionRun, run.id)
        assert stored_job is not None
        assert stored_job.result == {"question_count": 1}
        assert stored_run is not None
        assert stored_run.question_count == 1
        assert session.query(PracticeQuestion).count() == 1
    finally:
        session.close()


def test_practice_extraction_commits_progress_before_provider_call(client, stub_provider):
    session = get_session()
    try:
        _course, _practice, _answers, run, job = _seed_practice_run(session)
    finally:
        session.close()

    stub_provider.exceptions = [RuntimeError("provider down")]

    assert run_due_jobs_once() is True

    session = get_session()
    try:
        stored_job = session.get(Job, job.id)
        stored_run = session.get(PracticeExtractionRun, run.id)
        assert stored_job is not None
        assert stored_job.status == "failed"
        assert stored_job.progress == {
            "stage": "extracting",
            "pct": 10,
            "message": "extracting practice",
        }
        assert stored_run is not None
        assert stored_run.status == "queued"
    finally:
        session.close()


def test_practice_extraction_without_answer_sections_reports_failed_on_poll(client):
    session = get_session()
    try:
        course, practice, _answers, run, job = _seed_practice_run(session, with_answers=False)
    finally:
        session.close()

    assert run_due_jobs_once() is True

    session = get_session()
    try:
        stored_job = session.get(Job, job.id)
        stored_run = session.get(PracticeExtractionRun, run.id)
        assert stored_job is not None
        assert stored_job.status == "failed"
        assert stored_job.error == "no answer key sections found for practice section"
        assert stored_run is not None
        assert stored_run.status == "queued"
    finally:
        session.close()

    response = client.get(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["run_id"] == run.id
    assert body["job_id"] == job.id
    assert body["message"] == "Practice question extraction failed."
