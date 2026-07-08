from __future__ import annotations

import uuid

from app.db.engine import get_session
from app.db.models import Concept, Course, Job, PracticeExtractionRun, PracticeQuestion, Section


def _seed_practice_chapter(session):
    course = Course(title="Practice Course")
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
    )
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
    content = Section(
        id=f"content-{uuid.uuid4()}",
        course_id=course.id,
        order_index=0,
        title="0.1 Content - Fractions",
        body_md="Fractions content.",
        content_hash="content-hash",
        kind="content",
        chapter_label=practice.chapter_label,
    )
    session.add_all([practice, answers, content])
    session.commit()
    return course, practice, answers, content


def test_get_practice_assessment_reports_not_started_without_side_effect(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
    finally:
        session.close()

    response = client.get(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_started",
        "section_id": practice.id,
        "questions": [],
        "run_id": None,
        "job_id": None,
        "message": "Practice questions have not been extracted yet.",
    }

    session = get_session()
    try:
        assert session.query(PracticeExtractionRun).count() == 0
        assert session.query(Job).count() == 0
    finally:
        session.close()


def test_start_practice_assessment_starts_lazy_generation(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
    finally:
        session.close()

    response = client.post(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "generating"
    assert body["section_id"] == practice.id
    assert body["run_id"]
    assert body["job_id"]
    assert body["questions"] == []

    session = get_session()
    try:
        runs = session.query(PracticeExtractionRun).all()
        jobs = session.query(Job).all()
        assert len(runs) == 1
        assert len(jobs) == 1
        assert runs[0].job_id == jobs[0].id == body["job_id"]
        assert jobs[0].type == "generate_practice_assessment"
        assert jobs[0].payload == {
            "course_id": course.id,
            "section_id": practice.id,
            "run_id": body["run_id"],
        }
    finally:
        session.close()


def test_start_practice_assessment_reuses_existing_run(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
    finally:
        session.close()

    first = client.post(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")
    second = client.post(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["job_id"] == first.json()["job_id"]

    session = get_session()
    try:
        assert session.query(PracticeExtractionRun).count() == 1
        assert session.query(Job).count() == 1
    finally:
        session.close()


def test_get_practice_assessment_rejects_non_practice_section(client):
    session = get_session()
    try:
        course, _practice, _answers, content = _seed_practice_chapter(session)
    finally:
        session.close()

    response = client.get(f"/api/courses/{course.id}/sections/{content.id}/practice-assessment")

    assert response.status_code == 400
    assert response.json()["detail"] == "section is not a practice section"


def test_get_ready_practice_assessment_redacts_correct_index(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
        concept = Concept(
            course_id=course.id,
            slug="fractions.simplify",
            label="Simplifying Fractions",
            chapter_label=practice.chapter_label,
            section_id=practice.id,
        )
        session.add(concept)
        session.flush()
        question = PracticeQuestion(
            course_id=course.id,
            chapter_label=practice.chapter_label,
            section_id=practice.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="0.2 Practice - Fractions #1",
            stem_md="Simplify $42/12$.",
            choices=["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
            correct_index=0,
            explanation_md="$42/12 = 7/2$.",
            source_fingerprint="fingerprint-1",
            extraction_version="v3",
            confidence=0.99,
            status="ready",
        )
        session.add(question)
        session.commit()
    finally:
        session.close()

    response = client.get(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["run_id"] is None
    assert body["job_id"] is None
    assert body["message"] is None
    assert len(body["questions"]) == 1
    assert body["questions"][0]["choices"] == ["$7/2$", "$2/7$", "$3/4$", "$14/3$"]
    assert body["questions"][0]["concept"] == {
        "id": concept.id,
        "slug": "fractions.simplify",
        "label": "Simplifying Fractions",
    }
    assert body["questions"][0]["answered"] is None
    assert "correct_index" not in body["questions"][0]


def test_get_practice_assessment_sets_httponly_learner_cookie(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
    finally:
        session.close()

    response = client.get(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    cookie = response.headers["set-cookie"]
    assert "smv2_learner=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_get_practice_assessment_reports_failed_linked_job(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
        job = Job(
            type="generate_practice_assessment",
            status="failed",
            payload={"course_id": course.id, "section_id": practice.id},
            error="provider unavailable",
        )
        session.add(job)
        session.flush()
        run = PracticeExtractionRun(
            course_id=course.id,
            section_id=practice.id,
            status="queued",
            job_id=job.id,
            input_fingerprint="fingerprint",
        )
        session.add(run)
        session.commit()
        run_id = run.id
    finally:
        session.close()

    response = client.get(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["run_id"] == run_id
    assert body["job_id"] == job.id
    assert body["message"] == "Practice question extraction failed."

    session = get_session()
    try:
        stored_run = session.get(PracticeExtractionRun, run_id)
        assert stored_run is not None
        assert stored_run.status == "failed"
        assert stored_run.error == "provider unavailable"
    finally:
        session.close()
