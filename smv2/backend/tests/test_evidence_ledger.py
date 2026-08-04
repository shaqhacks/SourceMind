from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.engine import get_session
from app.db.models import (
    Card,
    Course,
    LearnerEvidenceEvent,
    ReviewLog,
    ReviewState,
    Section,
    Test,
)


def _card() -> tuple[str, str]:
    session = get_session()
    try:
        course = Course(title="Evidence ledger", status="ready")
        session.add(course)
        session.flush()
        section = Section(
            id=f"section-{uuid.uuid4()}",
            course_id=course.id,
            order_index=0,
            title="Evidence",
            body_md="Evidence source.",
            content_hash="ledger-source",
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


def test_card_grades_append_idempotent_normalized_events_with_spacing(client):
    _course_id, card_id = _card()

    assert client.post(f"/api/cards/{card_id}/grade", json={"grade": 1}).status_code == 200
    assert client.post(f"/api/cards/{card_id}/grade", json={"grade": 4}).status_code == 200

    session = get_session()
    try:
        events = (
            session.query(LearnerEvidenceEvent)
            .filter_by(channel="review")
            .order_by(LearnerEvidenceEvent.event_at)
            .all()
        )
        assert [event.normalized_outcome for event in events] == [0.0, 1.0]
        assert events[0].spacing_seconds is None
        assert events[1].spacing_seconds is not None
        assert events[1].spacing_seconds >= 0
        assert len({event.source_event_key for event in events}) == 2
    finally:
        session.close()


def test_quiz_submission_records_one_event_per_question_and_retry_adds_none(client):
    session = get_session()
    try:
        course = Course(title="Quiz ledger", status="ready")
        session.add(course)
        session.flush()
        test = Test(
            course_id=course.id,
            questions=[
                {
                    "question": "Q1",
                    "choices": ["A", "B", "C", "D"],
                    "correct_index": 0,
                    "explanation": "A",
                },
                {
                    "question": "Q2",
                    "choices": ["A", "B", "C", "D"],
                    "correct_index": 1,
                    "explanation": "B",
                },
            ],
        )
        session.add(test)
        session.commit()
        test_id = test.id
    finally:
        session.close()

    attempt = client.post(f"/api/tests/{test_id}/attempts").json()["attempt_id"]
    assert client.post(f"/api/tests/{attempt}/submit", json={"answers": [0, 0]}).status_code == 200
    assert client.post(f"/api/tests/{attempt}/submit", json={"answers": [0, 0]}).status_code == 409

    session = get_session()
    try:
        events = session.query(LearnerEvidenceEvent).filter_by(
            channel="quiz", attempt_id=attempt
        ).all()
        assert len(events) == 2
        assert sorted(event.normalized_outcome for event in events) == [0.0, 1.0]
    finally:
        session.close()


def test_grading_and_evidence_insert_roll_back_together(client, monkeypatch):
    _course_id, card_id = _card()

    def fail_record(*args, **kwargs):
        raise RuntimeError("evidence write failed")

    monkeypatch.setattr("app.services.srs_service.evidence_service.record_event", fail_record)
    with pytest.raises(RuntimeError, match="evidence write failed"):
        client.post(f"/api/cards/{card_id}/grade", json={"grade": 3})

    session = get_session()
    try:
        assert session.query(ReviewState).filter_by(card_id=card_id).count() == 0
        assert session.query(ReviewLog).filter_by(card_id=card_id).count() == 0
        assert session.query(LearnerEvidenceEvent).count() == 0
    finally:
        session.close()


def test_learner_evidence_history_rejects_updates(client):
    _course_id, card_id = _card()
    assert client.post(f"/api/cards/{card_id}/grade", json={"grade": 3}).status_code == 200

    session = get_session()
    try:
        event = session.query(LearnerEvidenceEvent).one()
        event.normalized_outcome = 0.0
        with pytest.raises((IntegrityError, OperationalError)):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_recording_evidence_rebuilds_the_affected_learner_projection(client, monkeypatch):
    _course_id, card_id = _card()
    calls = []

    def capture_rebuild(session, course_id, course_learning_profile_id, *, now):
        calls.append((course_id, course_learning_profile_id, now))
        return []

    monkeypatch.setattr(
        "app.services.learner_model.rebuild_profile",
        capture_rebuild,
    )
    assert client.post(f"/api/cards/{card_id}/grade", json={"grade": 3}).status_code == 200

    assert len(calls) == 1
    assert calls[0][0] == _course_id
    assert calls[0][1]
