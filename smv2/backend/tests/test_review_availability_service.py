from __future__ import annotations

import uuid
from datetime import timedelta

from conftest import _course_profile_id

from app.db.engine import get_session
from app.db.models import Card, Course, ReviewState, Section, utcnow
from app.services.learner_context import LEGACY_LOCAL_LEARNER_ID
from app.services.review_availability_service import get_review_availability


def test_review_availability_counts_mixed_course(client):
    session = get_session()
    try:
        course = Course(id=str(uuid.uuid4()), title="Availability Course", status="ready")
        session.add(course)
        section = Section(
            id=f"sec-{course.id}",
            course_id=course.id,
            order_index=0,
            title="Chapter 1",
            body_md="body",
            content_hash=f"hash-{course.id}",
            kind="content",
            chapter_label="Chapter 1",
        )
        session.add(section)
        session.commit()
        cards = [
            Card(
                id=f"card-{course.id}-{i}",
                course_id=course.id,
                section_id=section.id,
                front_md=f"front {i}",
                back_md=f"back {i}",
                position=i,
            )
            for i in range(5)
        ]
        session.add_all(cards)
        profile_id = _course_profile_id(session, course.id)
        now = utcnow()
        session.add_all(
            [
                ReviewState(
                    course_learning_profile_id=profile_id,
                    card_id=cards[0].id,
                    course_id=course.id,
                    due_at=now - timedelta(hours=1),
                    interval_days=1.0,
                    ease=2.5,
                    reps=1,
                    lapses=0,
                ),
                ReviewState(
                    course_learning_profile_id=profile_id,
                    card_id=cards[1].id,
                    course_id=course.id,
                    due_at=now + timedelta(days=3),
                    interval_days=3.0,
                    ease=2.5,
                    reps=2,
                    lapses=0,
                ),
            ]
        )
        session.commit()

        availability = get_review_availability(
            session, course.id, LEGACY_LOCAL_LEARNER_ID, now=now
        )

        assert availability.overdue_count == 1
        assert availability.new_count == 3
        assert availability.available_count == 4
        assert availability.total_count == 5
    finally:
        session.close()
