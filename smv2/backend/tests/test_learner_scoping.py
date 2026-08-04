from __future__ import annotations

import json
import uuid

from sqlalchemy import inspect
from fastapi.testclient import TestClient

from app.db.engine import get_engine, get_session
from app.db.models import (
    Card,
    Concept,
    ConceptMastery,
    Course,
    CourseLearningProfile,
    LearnerProfile,
    PracticeQuestion,
    ReviewLog,
    ReviewState,
    Section,
    Test,
    TestAttempt,
    utcnow,
)
from app.main import create_app
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from app.services.learner_context import ensure_course_learning_profile


def _seed_card() -> tuple[str, str]:
    session = get_session()
    try:
        course = Course(title="Learner isolation")
        session.add(course)
        session.flush()
        section = Section(
            id=f"section-{uuid.uuid4()}",
            course_id=course.id,
            order_index=0,
            title="Foundations",
            body_md="Foundational material.",
            content_hash="learner-isolation-foundations",
        )
        session.add(section)
        session.flush()
        card = Card(
            id=f"card-{uuid.uuid4()}",
            course_id=course.id,
            section_id=section.id,
            front_md="Question",
            back_md="Answer",
            position=0,
        )
        session.add(card)
        session.commit()
        return course.id, card.id
    finally:
        session.close()


def _seed_test() -> tuple[str, str]:
    session = get_session()
    try:
        course = Course(title="Quiz isolation")
        session.add(course)
        session.flush()
        test = Test(
            course_id=course.id,
            questions=[
                {
                    "question": "Which answer is correct?",
                    "choices": ["A", "B", "C", "D"],
                    "correct_index": 0,
                    "explanation": "A is correct.",
                }
            ],
        )
        session.add(test)
        session.commit()
        return course.id, test.id
    finally:
        session.close()


def _seed_practice_question() -> tuple[str, str, str]:
    session = get_session()
    try:
        course = Course(title="Practice isolation")
        session.add(course)
        session.flush()
        section = Section(
            id=f"practice-{uuid.uuid4()}",
            course_id=course.id,
            order_index=0,
            title="Practice",
            body_md="Practice material.",
            content_hash="learner-isolation-practice",
            kind="practice",
        )
        session.add(section)
        session.flush()
        concept = Concept(
            course_id=course.id,
            slug="practice-concept",
            label="Practice concept",
            section_id=section.id,
        )
        session.add(concept)
        session.flush()
        question = PracticeQuestion(
            course_id=course.id,
            section_id=section.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="Practice #1",
            stem_md="Choose A.",
            choices=["A", "B", "C", "D"],
            correct_index=0,
            explanation_md="A is correct.",
            source_fingerprint="practice-isolation-question",
            extraction_version="v3",
            confidence=1.0,
            status="ready",
        )
        session.add(question)
        session.commit()
        return course.id, section.id, question.id
    finally:
        session.close()


def test_review_grade_establishes_secure_learner_cookie(client):
    _course_id, card_id = _seed_card()

    response = client.post(f"/api/cards/{card_id}/grade", json={"grade": 3})

    assert response.status_code == 200
    learner_key = client.cookies.get("smv2_learner")
    assert learner_key is not None
    assert str(uuid.UUID(learner_key)) == learner_key
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_schema_has_stable_learner_and_course_learning_profile(client):
    tables = set(inspect(get_engine()).get_table_names())

    assert "learner_profiles" in tables
    assert "course_learning_profiles" in tables


def test_review_grade_persists_one_course_profile_for_the_learner(client):
    course_id, card_id = _seed_card()

    assert client.post(f"/api/cards/{card_id}/grade", json={"grade": 3}).status_code == 200

    learner_id = client.cookies.get("smv2_learner")
    session = get_session()
    try:
        assert session.get(LearnerProfile, learner_id) is not None
        profiles = (
            session.query(CourseLearningProfile)
            .filter_by(learner_id=learner_id, course_id=course_id)
            .all()
        )
        assert len(profiles) == 1
    finally:
        session.close()


def test_two_learners_have_independent_review_state_for_the_same_card(client):
    _course_id, card_id = _seed_card()

    assert client.post(f"/api/cards/{card_id}/grade", json={"grade": 4}).status_code == 200
    with TestClient(create_app()) as other_learner:
        assert other_learner.post(
            f"/api/cards/{card_id}/grade", json={"grade": 1}
        ).status_code == 200
        assert other_learner.cookies.get("smv2_learner") != client.cookies.get("smv2_learner")

    session = get_session()
    try:
        states = session.query(ReviewState).filter_by(card_id=card_id).all()
        assert len(states) == 2
        assert sorted(state.last_grade for state in states) == [1, 4]
        logs = session.query(ReviewLog).filter_by(card_id=card_id).all()
        assert len(logs) == 2
        assert len({log.course_learning_profile_id for log in logs}) == 2
    finally:
        session.close()


def test_review_queue_is_scoped_to_requesting_learner(client):
    course_id, card_id = _seed_card()
    assert client.post(f"/api/cards/{card_id}/grade", json={"grade": 4}).status_code == 200

    first_queue = client.get(f"/api/courses/{course_id}/review/queue")
    assert first_queue.status_code == 200
    assert first_queue.json()["cards"] == []

    with TestClient(create_app()) as other_learner:
        second_queue = other_learner.get(f"/api/courses/{course_id}/review/queue")
        assert second_queue.status_code == 200
        assert other_learner.cookies.get("smv2_learner") is not None
        assert [card["id"] for card in second_queue.json()["cards"]] == [card_id]
        assert second_queue.json()["cards"][0]["is_new"] is True


def test_two_learners_create_independently_owned_quiz_attempts(client):
    _course_id, test_id = _seed_test()

    first = client.post(f"/api/tests/{test_id}/attempts")
    assert first.status_code == 201
    assert client.cookies.get("smv2_learner") is not None

    with TestClient(create_app()) as other_learner:
        second = other_learner.post(f"/api/tests/{test_id}/attempts")
        assert second.status_code == 201
        assert other_learner.cookies.get("smv2_learner") != client.cookies.get("smv2_learner")

    attempt_ids = [first.json()["attempt_id"], second.json()["attempt_id"]]
    session = get_session()
    try:
        attempts = session.query(TestAttempt).filter(TestAttempt.id.in_(attempt_ids)).all()
        assert len(attempts) == 2
        assert len({attempt.course_learning_profile_id for attempt in attempts}) == 2
    finally:
        session.close()


def test_quiz_attempt_cannot_be_read_or_submitted_by_another_learner(client):
    _course_id, test_id = _seed_test()
    created = client.post(f"/api/tests/{test_id}/attempts")
    attempt_id = created.json()["attempt_id"]

    assert client.get(f"/api/tests/{attempt_id}").status_code == 200
    with TestClient(create_app()) as other_learner:
        assert other_learner.get(f"/api/tests/{attempt_id}").status_code == 404
        assert other_learner.post(
            f"/api/tests/{attempt_id}/submit", json={"answers": [0]}
        ).status_code == 404


def test_generated_quiz_attempt_is_owned_by_requesting_learner(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(
            text=json.dumps(
                [
                    {
                        "question": "Which answer is correct?",
                        "choices": ["A", "B", "C", "D"],
                        "correct_index": 0,
                        "explanation": "A is correct.",
                    }
                ]
            ),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        )
    ]

    response = client.post(f"/api/courses/{course_id}/tests")

    assert response.status_code == 202
    learner_id = client.cookies.get("smv2_learner")
    assert learner_id is not None
    assert run_due_jobs_once() is True
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    attempt_id = job["result"]["attempt_id"]

    session = get_session()
    try:
        attempt = session.get(TestAttempt, attempt_id)
        profile = session.get(CourseLearningProfile, attempt.course_learning_profile_id)
        assert profile.learner_id == learner_id
        assert profile.course_id == course_id
    finally:
        session.close()


def test_quiz_submission_seeds_review_state_for_the_same_course_profile(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(
            text=json.dumps(
                [
                    {
                        "question": "Which answer is correct?",
                        "choices": ["A", "B", "C", "D"],
                        "correct_index": 0,
                        "explanation": "A is correct.",
                    }
                ]
            ),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        )
    ]
    generated = client.post(f"/api/courses/{course_id}/tests")
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{generated.json()['job_id']}").json()["result"][
        "attempt_id"
    ]

    submitted = client.post(f"/api/tests/{attempt_id}/submit", json={"answers": [0]})

    assert submitted.status_code == 200
    session = get_session()
    try:
        attempt = session.get(TestAttempt, attempt_id)
        states = session.query(ReviewState).filter_by(course_id=course_id).all()
        assert states
        assert {state.course_learning_profile_id for state in states} == {
            attempt.course_learning_profile_id
        }
    finally:
        session.close()


def test_skill_map_ignores_legacy_mastery_rows_for_every_learner(client):
    learner_a = str(uuid.uuid4())
    learner_b = str(uuid.uuid4())
    session = get_session()
    try:
        course = Course(title="Skill isolation")
        session.add(course)
        session.flush()
        concept = Concept(course_id=course.id, slug="fractions", label="Fractions")
        session.add(concept)
        session.flush()
        session.add_all(
            [
                ConceptMastery(
                    course_id=course.id,
                    concept_id=concept.id,
                    learner_key=learner_a,
                    points=4,
                    correct_count=4,
                    wrong_count=0,
                ),
                ConceptMastery(
                    course_id=course.id,
                    concept_id=concept.id,
                    learner_key=learner_b,
                    points=-4,
                    correct_count=0,
                    wrong_count=4,
                ),
            ]
        )
        session.commit()
        course_id = course.id
    finally:
        session.close()

    client.cookies.set("smv2_learner", learner_a)
    first = client.get(f"/api/courses/{course_id}/skills")
    with TestClient(create_app(), cookies={"smv2_learner": learner_b}) as other_learner:
        second = other_learner.get(f"/api/courses/{course_id}/skills")

    assert first.status_code == 200
    assert second.status_code == 200
    for response in (first, second):
        node = response.json()["nodes"][0]
        assert node["readiness_estimate"] is None
        assert node["evidence_state"] == "insufficient_evidence"
        assert "mastery" not in node


def test_practice_submission_uses_shared_course_learning_profile(client):
    course_id, section_id, question_id = _seed_practice_question()

    response = client.post(
        f"/api/courses/{course_id}/practice-questions/{question_id}/answer",
        json={"selected_index": 0},
    )

    assert response.status_code == 200
    learner_id = client.cookies.get("smv2_learner")
    session = get_session()
    try:
        profiles = (
            session.query(CourseLearningProfile)
            .filter_by(learner_id=learner_id, course_id=course_id)
            .all()
        )
        assert len(profiles) == 1
    finally:
        session.close()


def test_test_list_contains_only_requesting_learners_attempt_history(client):
    course_id, test_id = _seed_test()
    learner_a = str(uuid.uuid4())
    learner_b = str(uuid.uuid4())
    session = get_session()
    try:
        profile_a = ensure_course_learning_profile(session, learner_a, course_id)
        profile_b = ensure_course_learning_profile(session, learner_b, course_id)
        session.add_all(
            [
                TestAttempt(
                    test_id=test_id,
                    course_id=course_id,
                    course_learning_profile_id=profile_a.id,
                    score=0.25,
                ),
                TestAttempt(
                    test_id=test_id,
                    course_id=course_id,
                    course_learning_profile_id=profile_b.id,
                    score=1.0,
                ),
            ]
        )
        session.commit()
    finally:
        session.close()

    client.cookies.set("smv2_learner", learner_a)
    response_a = client.get(f"/api/courses/{course_id}/tests")
    with TestClient(create_app(), cookies={"smv2_learner": learner_b}) as other_learner:
        response_b = other_learner.get(f"/api/courses/{course_id}/tests")

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert [attempt["score"] for attempt in response_a.json()[0]["attempts"]] == [0.25]
    assert [attempt["score"] for attempt in response_b.json()[0]["attempts"]] == [1.0]


def test_chapter_stats_and_study_suggestions_use_only_requesting_learner(client):
    learner_a = str(uuid.uuid4())
    learner_b = str(uuid.uuid4())
    session = get_session()
    try:
        course = Course(title="Recommendation isolation", status="ready")
        session.add(course)
        session.flush()
        chapter_label = "Chapter 1: Foundations"
        session.add(
            Section(
                id=f"section-{uuid.uuid4()}",
                course_id=course.id,
                order_index=0,
                title="Foundations",
                body_md="Foundational material.",
                content_hash="recommendation-isolation-foundations",
                chapter_label=chapter_label,
            )
        )
        test = Test(
            course_id=course.id,
            chapter_label=chapter_label,
            questions=[{"question": "Q"}],
        )
        session.add(test)
        session.flush()
        profile_a = ensure_course_learning_profile(session, learner_a, course.id)
        profile_b = ensure_course_learning_profile(session, learner_b, course.id)
        session.add_all(
            [
                TestAttempt(
                    test_id=test.id,
                    course_id=course.id,
                    course_learning_profile_id=profile_a.id,
                    score=0.25,
                ),
                TestAttempt(
                    test_id=test.id,
                    course_id=course.id,
                    course_learning_profile_id=profile_b.id,
                    score=1.0,
                ),
            ]
        )
        session.commit()
        course_id = course.id
    finally:
        session.close()

    client.cookies.set("smv2_learner", learner_a)
    chapters_a = client.get(f"/api/courses/{course_id}/chapters")
    suggestions_a = client.get(f"/api/courses/{course_id}/study-next")
    with TestClient(create_app(), cookies={"smv2_learner": learner_b}) as other_learner:
        chapters_b = other_learner.get(f"/api/courses/{course_id}/chapters")
        suggestions_b = other_learner.get(f"/api/courses/{course_id}/study-next")

    assert chapters_a.status_code == 200
    assert chapters_b.status_code == 200
    assert chapters_a.json()[0]["test_stats"]["best_score"] == 0.25
    assert chapters_b.json()[0]["test_stats"]["best_score"] == 1.0
    assert any(item["reason"] == "low_test_score" for item in suggestions_a.json())
    assert all(item["reason"] != "low_test_score" for item in suggestions_b.json())


def test_due_card_recommendations_ignore_another_learners_schedule(client):
    learner_a = str(uuid.uuid4())
    learner_b = str(uuid.uuid4())
    session = get_session()
    try:
        course = Course(title="Due-card isolation", status="ready")
        session.add(course)
        session.flush()
        chapter_label = "Chapter 1: Review"
        section = Section(
            id=f"section-{uuid.uuid4()}",
            course_id=course.id,
            order_index=0,
            title="Review",
            body_md="Review material.",
            content_hash="due-card-isolation",
            chapter_label=chapter_label,
        )
        session.add(section)
        session.flush()
        profile_b = ensure_course_learning_profile(session, learner_b, course.id)
        for position in range(5):
            card = Card(
                id=f"card-{uuid.uuid4()}",
                course_id=course.id,
                section_id=section.id,
                front_md=f"Question {position}",
                back_md="Answer",
                position=position,
            )
            session.add(card)
            session.flush()
            session.add(
                ReviewState(
                    course_learning_profile_id=profile_b.id,
                    card_id=card.id,
                    course_id=course.id,
                    due_at=utcnow().replace(year=utcnow().year + 1),
                    interval_days=365.0,
                    ease=2.5,
                )
            )
        session.commit()
        course_id = course.id
    finally:
        session.close()

    client.cookies.set("smv2_learner", learner_a)
    response_a = client.get(f"/api/courses/{course_id}/study-next")
    with TestClient(create_app(), cookies={"smv2_learner": learner_b}) as other_learner:
        response_b = other_learner.get(f"/api/courses/{course_id}/study-next")

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert any(
        item["reason"] == "due_cards" and item["detail"]["due_count"] == 5
        for item in response_a.json()
    )
    assert all(item["reason"] != "due_cards" for item in response_b.json())
