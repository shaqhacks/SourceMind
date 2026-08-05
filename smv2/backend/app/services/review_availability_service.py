from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_

from app.db.models import Card, CourseLearningProfile, ReviewState


@dataclass(frozen=True)
class ReviewAvailability:
    overdue_count: int
    new_count: int
    available_count: int
    total_count: int


def get_review_availability(
    session,
    course_id: str,
    learner_id: str,
    *,
    now: datetime,
    section_ids: list[str] | None = None,
) -> ReviewAvailability:
    course_profile_id = (
        session.query(CourseLearningProfile.id)
        .filter_by(learner_id=learner_id, course_id=course_id)
        .scalar()
    )
    card_filters = [Card.course_id == course_id]
    if section_ids is not None:
        if not section_ids:
            return ReviewAvailability(
                overdue_count=0,
                new_count=0,
                available_count=0,
                total_count=0,
            )
        card_filters.append(Card.section_id.in_(section_ids))

    if course_profile_id is None:
        overdue_count = 0
        new_count = session.query(Card).filter(*card_filters).count()
    else:
        overdue_count = (
            session.query(Card)
            .join(
                ReviewState,
                and_(
                    ReviewState.card_id == Card.id,
                    ReviewState.course_learning_profile_id == course_profile_id,
                ),
            )
            .filter(*card_filters, ReviewState.due_at <= now)
            .count()
        )
        new_count = (
            session.query(Card)
            .outerjoin(
                ReviewState,
                and_(
                    ReviewState.card_id == Card.id,
                    ReviewState.course_learning_profile_id == course_profile_id,
                ),
            )
            .filter(*card_filters, ReviewState.card_id.is_(None))
            .count()
        )
    total_count = session.query(Card).filter(*card_filters).count()
    return ReviewAvailability(
        overdue_count=overdue_count,
        new_count=new_count,
        available_count=overdue_count + new_count,
        total_count=total_count,
    )
