"""ADR-022: deterministic study-suggestion triage (app.services.study_service).
Each tier is tested against a minimal, directly-constructed course/section
set (no full ingest needed) so each scenario is isolated and unambiguous,
matching the pure-function testing style test_srs_schedule.py already uses
for schedule_next.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from conftest import _course_profile_id

from app.db.engine import get_session
from app.db.models import Card, Course, ProgressState, ReviewState, Section, Test, TestAttempt, utcnow
from app.services.study_service import study_next


def _make_course(session, n_chapters: int) -> tuple[str, list[str]]:
    course = Course(id=str(uuid.uuid4()), title="Study Next Test Course", status="ready")
    session.add(course)
    labels = [f"Chapter {i + 1}: Topic {i + 1}" for i in range(n_chapters)]
    for i, label in enumerate(labels):
        session.add(
            Section(
                id=f"sec-{course.id}-{i}",
                course_id=course.id,
                order_index=i,
                title=label,
                body_md="body",
                content_hash=f"hash-{course.id}-{i}",
                kind="content",
                chapter_label=label,
            )
        )
    session.commit()
    return course.id, labels


def _add_graded_test(session, course_id: str, chapter_label: str, score: float) -> None:
    test = Test(course_id=course_id, chapter_label=chapter_label, questions=[{"q": 1}])
    session.add(test)
    session.flush()
    session.add(
        TestAttempt(
            test_id=test.id,
            course_id=course_id,
            course_learning_profile_id=_course_profile_id(session, course_id),
            score=score,
        )
    )
    session.commit()


def _add_due_cards(session, section_id: str, course_id: str, count: int) -> None:
    for i in range(count):
        card_id = f"card-{section_id}-{i}"
        session.add(
            Card(
                id=card_id, course_id=course_id, section_id=section_id,
                front_md="f", back_md="b", position=i,
            )
        )
    session.commit()


def _add_reviewed_due_cards(session, section_id: str, course_id: str, count: int) -> None:
    profile_id = _course_profile_id(session, course_id)
    now = utcnow()
    for i in range(count):
        card_id = f"reviewed-card-{section_id}-{i}"
        session.add(
            Card(
                id=card_id, course_id=course_id, section_id=section_id,
                front_md="f", back_md="b", position=100 + i,
            )
        )
        session.flush()
        session.add(
            ReviewState(
                course_learning_profile_id=profile_id,
                card_id=card_id,
                course_id=course_id,
                due_at=now - timedelta(hours=1),
                interval_days=1.0,
                ease=2.5,
                reps=1,
                lapses=0,
            )
        )
    session.commit()


def test_study_next_tier_a_low_score_worst_first(client):
    session = get_session()
    try:
        course_id, labels = _make_course(session, 2)
        _add_graded_test(session, course_id, labels[0], score=0.5)
        _add_graded_test(session, course_id, labels[1], score=0.2)

        result = study_next(course_id, limit=3)
        low_score = [s for s in result if s["reason"] == "low_test_score"]
        assert [s["chapter_label"] for s in low_score] == [labels[1], labels[0]]  # worst first
    finally:
        session.close()


def test_study_next_ignores_scores_at_or_above_threshold(client):
    session = get_session()
    try:
        course_id, labels = _make_course(session, 1)
        _add_graded_test(session, course_id, labels[0], score=0.8)

        result = study_next(course_id, limit=3)
        assert all(s["chapter_label"] != labels[0] or s["reason"] != "low_test_score" for s in result)
    finally:
        session.close()


def test_study_next_tier_b_new_cards_threshold(client):
    session = get_session()
    try:
        course_id, labels = _make_course(session, 2)
        section_ids = [
            s.id for s in session.query(Section).filter(Section.course_id == course_id).order_by(Section.order_index)
        ]
        _add_due_cards(session, section_ids[0], course_id, count=6)  # new-card availability over threshold
        _add_due_cards(session, section_ids[1], course_id, count=2)  # under threshold

        result = study_next(course_id, limit=3)
        new_reasons = {s["chapter_label"]: s for s in result if s["reason"] == "new_cards"}
        assert labels[0] in new_reasons
        assert new_reasons[labels[0]]["detail"]["new_count"] == 6
        assert new_reasons[labels[0]]["detail"]["overdue_count"] == 0
        assert labels[1] not in new_reasons
    finally:
        session.close()


def test_study_next_tier_b_due_cards_uses_overdue_backlog(client):
    session = get_session()
    try:
        course_id, labels = _make_course(session, 1)
        section_id = (
            session.query(Section.id)
            .filter(Section.course_id == course_id)
            .order_by(Section.order_index)
            .scalar()
        )
        _add_reviewed_due_cards(session, section_id, course_id, count=6)

        result = study_next(course_id, limit=3)

        due = next(s for s in result if s["chapter_label"] == labels[0])
        assert due["reason"] == "due_cards"
        assert due["detail"]["due_count"] == 6
        assert due["detail"]["overdue_count"] == 6
        assert due["detail"]["new_count"] == 0
    finally:
        session.close()


def test_study_next_mixed_due_and_new_cards_reports_both_without_calling_new_due(client):
    session = get_session()
    try:
        course_id, labels = _make_course(session, 1)
        section_id = (
            session.query(Section.id)
            .filter(Section.course_id == course_id)
            .order_by(Section.order_index)
            .scalar()
        )
        _add_reviewed_due_cards(session, section_id, course_id, count=3)
        _add_due_cards(session, section_id, course_id, count=4)

        result = study_next(course_id, limit=3)

        due = next(s for s in result if s["chapter_label"] == labels[0])
        assert due["reason"] == "due_cards"
        assert due["detail"]["overdue_count"] == 3
        assert due["detail"]["new_count"] == 4
        assert due["detail"]["available_count"] == 7
        assert due["detail"]["due_count"] == 3
    finally:
        session.close()


def test_study_next_tier_c_unread_course_suggests_first_chapter_only(client):
    session = get_session()
    try:
        course_id, labels = _make_course(session, 3)
        # No ProgressState at all for this course.
        result = study_next(course_id, limit=3)
        unread = [s for s in result if s["reason"] == "unread"]
        assert len(unread) == 1
        assert unread[0]["chapter_label"] == labels[0]  # first in course order
    finally:
        session.close()


def test_study_next_tier_d_stale_chapters_weighted_by_score(client):
    session = get_session()
    try:
        course_id, labels = _make_course(session, 2)
        _add_graded_test(session, course_id, labels[0], score=0.9)  # mastered
        _add_graded_test(session, course_id, labels[1], score=0.4)  # below low-score threshold too

        old = utcnow() - timedelta(days=30)
        session.add(ProgressState(course_id=course_id, section_id=None, scroll_pos=0.0, updated_at=old))
        session.commit()

        result = study_next(course_id, limit=3)
        # labels[1] qualifies for tier (a) (low score) first -- tier (d)
        # only ever surfaces chapters NOT already suggested by an earlier
        # tier, so it should show up as low_test_score, not stale.
        by_label = {s["chapter_label"]: s for s in result}
        assert by_label[labels[1]]["reason"] == "low_test_score"
        # labels[0] (mastered, 0.9) isn't low-score or due-heavy or unread
        # (ProgressState exists) -- it surfaces via staleness instead.
        assert by_label[labels[0]]["reason"] == "stale"
        assert by_label[labels[0]]["detail"]["days_since"] >= 30
    finally:
        session.close()


def test_study_next_no_suggestions_for_a_fresh_untouched_course_with_progress(client):
    """A course that HAS been opened (ProgressState exists), updated just
    now, with no tests/due cards at all -- nothing should be suggested
    (days_since == 0, so tier (d)'s priority is 0 for everything).
    """
    session = get_session()
    try:
        course_id, labels = _make_course(session, 2)
        session.add(ProgressState(course_id=course_id, section_id=None, scroll_pos=0.0))
        session.commit()

        result = study_next(course_id, limit=3)
        assert result == []
    finally:
        session.close()


def test_study_next_respects_limit(client):
    session = get_session()
    try:
        course_id, labels = _make_course(session, 5)
        for label in labels:
            _add_graded_test(session, course_id, label, score=0.1)

        result = study_next(course_id, limit=3)
        assert len(result) == 3
    finally:
        session.close()


def test_study_next_ignores_front_matter_none_label(client):
    """A section with no chapter_label (the "Front matter" group,
    client-labeled) must never be suggested -- there's nothing coherent to
    point a learner at.
    """
    session = get_session()
    try:
        course = Course(id=str(uuid.uuid4()), title="No chapters course", status="ready")
        session.add(course)
        session.add(
            Section(
                id=f"sec-{course.id}",
                course_id=course.id,
                order_index=0,
                title="Preface",
                body_md="body",
                content_hash="hash",
                kind="content",
                chapter_label=None,
            )
        )
        session.commit()

        result = study_next(course.id, limit=3)
        assert result == []
    finally:
        session.close()


def test_get_study_next_endpoint_returns_suggestions(client, ingest_course):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    resp = client.get(f"/api/courses/{course_id}/study-next")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    # This fixture has never been opened -- expect the "unread" suggestion.
    assert any(s["reason"] == "unread" for s in body)


def test_get_study_next_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/study-next")
    assert resp.status_code == 404
