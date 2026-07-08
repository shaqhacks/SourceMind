from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

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


def _seed_ready_question(session, *, correct_index=0):
    course, practice, answers, content = _seed_practice_chapter(session)
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
        correct_index=correct_index,
        explanation_md="$42/12 = 7/2$.",
        source_fingerprint="fingerprint-1",
        extraction_version="v3",
        confidence=0.99,
        status="ready",
    )
    session.add(question)
    session.commit()
    return course, practice, answers, content, concept, question


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
    cookie = response.headers["set-cookie"]
    assert "smv2_learner=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
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
    learner_key = client.cookies.get("smv2_learner")
    assert learner_key is not None
    assert "set-cookie" in first.headers
    assert "set-cookie" not in second.headers
    assert client.cookies.get("smv2_learner") == learner_key
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


def test_get_practice_assessment_does_not_set_learner_cookie(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
    finally:
        session.close()

    response = client.get(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers


def test_get_practice_assessment_reports_failed_linked_job_without_mutating_run(client):
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
    assert "set-cookie" not in response.headers

    session = get_session()
    try:
        stored_run = session.get(PracticeExtractionRun, run_id)
        assert stored_run is not None
        assert stored_run.status == "queued"
        assert stored_run.error is None
    finally:
        session.close()


def test_start_practice_assessment_retries_failed_linked_job_with_new_job(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
    finally:
        session.close()

    first = client.post(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")
    assert first.status_code == 202
    first_body = first.json()

    session = get_session()
    try:
        run = session.get(PracticeExtractionRun, first_body["run_id"])
        assert run is not None
        job = session.get(Job, first_body["job_id"])
        assert job is not None
        job.status = "failed"
        job.error = "provider unavailable"
        session.commit()
    finally:
        session.close()

    second = client.post(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert second.status_code == 202
    second_body = second.json()
    assert second_body["status"] == "generating"
    assert second_body["run_id"] == first_body["run_id"]
    assert second_body["job_id"] != first_body["job_id"]

    session = get_session()
    try:
        assert session.query(PracticeExtractionRun).count() == 1
        assert session.query(Job).count() == 2
        stored_run = session.get(PracticeExtractionRun, first_body["run_id"])
        assert stored_run is not None
        assert stored_run.status == "queued"
        assert stored_run.error is None
        assert stored_run.job_id == second_body["job_id"]
        retry_job = session.get(Job, second_body["job_id"])
        assert retry_job is not None
        assert retry_job.payload == {
            "course_id": course.id,
            "section_id": practice.id,
            "run_id": first_body["run_id"],
        }
    finally:
        session.close()


def test_start_practice_assessment_retries_failed_run_with_new_job(client):
    session = get_session()
    try:
        course, practice, _answers, _content = _seed_practice_chapter(session)
    finally:
        session.close()

    first = client.post(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")
    assert first.status_code == 202
    first_body = first.json()

    session = get_session()
    try:
        run = session.get(PracticeExtractionRun, first_body["run_id"])
        assert run is not None
        original_job = session.get(Job, first_body["job_id"])
        assert original_job is not None
        run.status = "failed"
        run.error = "provider unavailable"
        session.commit()
    finally:
        session.close()

    second = client.post(f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment")

    assert second.status_code == 202
    second_body = second.json()
    assert second_body["status"] == "generating"
    assert second_body["run_id"] == first_body["run_id"]
    assert second_body["job_id"] != first_body["job_id"]

    session = get_session()
    try:
        assert session.query(PracticeExtractionRun).count() == 1
        assert session.query(Job).count() == 2
        stored_run = session.get(PracticeExtractionRun, first_body["run_id"])
        assert stored_run is not None
        assert stored_run.status == "queued"
        assert stored_run.error is None
        assert stored_run.job_id == second_body["job_id"]
    finally:
        session.close()


def test_answer_endpoint_sets_learner_cookie_and_reveals_answer(client):
    session = get_session()
    try:
        course, _practice, _answers, _content, _concept, question = _seed_ready_question(session)
    finally:
        session.close()

    response = client.post(
        f"/api/courses/{course.id}/practice-questions/{question.id}/answer",
        json={"selected_index": 1},
    )

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "smv2_learner=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    body = response.json()
    assert body["question_id"] == question.id
    assert body["correct"] is False
    assert body["correct_index"] == 0
    assert body["points_delta"] == -1
    assert body["explanation_md"] == "$42/12 = 7/2$."


def test_answer_endpoint_rejects_out_of_range_choice(client):
    session = get_session()
    try:
        course, _practice, _answers, _content, _concept, question = _seed_ready_question(session)
    finally:
        session.close()

    response = client.post(
        f"/api/courses/{course.id}/practice-questions/{question.id}/answer",
        json={"selected_index": 4},
    )

    assert response.status_code == 422


def test_answer_endpoint_rejects_boolean_choice(client):
    session = get_session()
    try:
        course, _practice, _answers, _content, _concept, question = _seed_ready_question(session)
    finally:
        session.close()

    response = client.post(
        f"/api/courses/{course.id}/practice-questions/{question.id}/answer",
        json={"selected_index": True},
    )

    assert response.status_code == 422


def test_ready_assessment_includes_answered_summary_for_same_learner_only(client):
    session = get_session()
    try:
        course, practice, _answers, _content, _concept, question = _seed_ready_question(session)
    finally:
        session.close()

    answer_response = client.post(
        f"/api/courses/{course.id}/practice-questions/{question.id}/answer",
        json={"selected_index": 1},
    )
    assert answer_response.status_code == 200

    same_learner = client.get(
        f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment"
    )
    assert same_learner.status_code == 200
    answered = same_learner.json()["questions"][0]["answered"]
    assert answered["selected_index"] == 1
    assert answered["correct"] is False
    assert answered["correct_index"] == 0
    assert answered["explanation_md"] == "$42/12 = 7/2$."
    assert answered["points_delta"] == -1
    assert answered["mastery_points"] == -1
    assert answered["answered_at"]

    with TestClient(client.app) as fresh_client:
        fresh_response = fresh_client.get(
            f"/api/courses/{course.id}/sections/{practice.id}/practice-assessment"
        )
    assert fresh_response.status_code == 200
    assert fresh_response.json()["questions"][0]["answered"] is None


def test_answer_endpoint_does_not_grade_wrong_course_question(client):
    session = get_session()
    try:
        _course, _practice, _answers, _content, _concept, question = _seed_ready_question(session)
        other_course = Course(title="Other Course")
        session.add(other_course)
        session.commit()
        other_course_id = other_course.id
    finally:
        session.close()

    response = client.post(
        f"/api/courses/{other_course_id}/practice-questions/{question.id}/answer",
        json={"selected_index": 0},
    )

    assert response.status_code == 404
