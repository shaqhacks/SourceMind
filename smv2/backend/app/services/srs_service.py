"""Deterministic SM-2-variant spaced repetition scheduler — schedule_next()
is a pure function of the card's current review state, no LLM involved,
ever. Grades: 1=Again, 2=Hard, 3=Good, 4=Easy.

Interpretive choices beyond the literal brief (documented here since the
source spec left them implicit and a reviewer should be able to see the
reasoning rather than have to reverse-engineer it from the numbers):
- `reps` counts consecutive non-Again grades, reset to 0 on Again.
- The first two non-Again reviews (reps 0 and 1) use fixed baseline
  intervals of 1 day and 6 days respectively (classic SM-2 behavior) for
  Hard/Good/Easy alike, not just Good — otherwise a brand-new card's
  interval_days=0 would multiply out to 0 regardless of grade. Good's
  bootstrap intervals (1d/6d) are used as-is, with no ease multiplier,
  matching "first Good: 1d, second: 6d" literally; Easy's bootstrap applies
  its 1.3x bonus on top of that same baseline but likewise skips the ease
  multiplier until reps >= 2 (ease hasn't been "proven" over enough
  repetitions yet to trust multiplying by it).
- Interval multiplications that DO use ease use the ease factor as it was
  BEFORE this grade's adjustment — the adjustment takes effect for the
  NEXT review, not retroactively for this one.
- Ease reductions (Again, Hard) are floored at 1.3; ease increases (Easy)
  have no ceiling (spec doesn't call for one).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func

from app.db.engine import get_session
from app.db.models import (
    Card,
    Course,
    ReviewLog,
    ReviewState,
    Section,
    ensure_utc,
    utcnow,
)
from app.services import evidence_items_service, evidence_service, learner_context
from app.services.review_availability_service import get_review_availability

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
_VALID_GRADES = {AGAIN, HARD, GOOD, EASY}

DEFAULT_EASE = 2.5
_MIN_EASE = 1.3
_AGAIN_DUE_MINUTES = 10
_FIRST_INTERVAL_DAYS = 1.0
_SECOND_INTERVAL_DAYS = 6.0
_EASY_BONUS = 1.3


@dataclass
class ScheduleResult:
    interval_days: float
    ease: float
    due_at: datetime
    reps: int
    lapses_delta: int


def _baseline_interval(current_interval_days: float, reps: int) -> float:
    if reps == 0:
        return _FIRST_INTERVAL_DAYS
    if reps == 1:
        return _SECOND_INTERVAL_DAYS
    return current_interval_days


def schedule_next(grade: int, *, interval_days: float, ease: float, reps: int) -> ScheduleResult:
    """Pure function: given the CURRENT state (before this grade) and the
    grade just given, returns the NEXT state.
    """
    if grade not in _VALID_GRADES:
        raise ValueError(f"invalid grade: {grade} (must be 1-4)")

    now = utcnow()

    if grade == AGAIN:
        new_ease = max(_MIN_EASE, ease - 0.2)
        return ScheduleResult(
            interval_days=0.0,
            ease=new_ease,
            due_at=now + timedelta(minutes=_AGAIN_DUE_MINUTES),
            reps=0,
            lapses_delta=1,
        )

    baseline = _baseline_interval(interval_days, reps)

    if grade == HARD:
        new_ease = max(_MIN_EASE, ease - 0.15)
        new_interval = baseline * 1.2
        return ScheduleResult(
            interval_days=new_interval,
            ease=new_ease,
            due_at=now + timedelta(days=new_interval),
            reps=reps + 1,
            lapses_delta=0,
        )

    if grade == GOOD:
        new_interval = baseline if reps < 2 else baseline * ease
        return ScheduleResult(
            interval_days=new_interval,
            ease=ease,
            due_at=now + timedelta(days=new_interval),
            reps=reps + 1,
            lapses_delta=0,
        )

    # EASY
    new_ease = ease + 0.15
    new_interval = (baseline if reps < 2 else baseline * ease) * _EASY_BONUS
    return ScheduleResult(
        interval_days=new_interval,
        ease=new_ease,
        due_at=now + timedelta(days=new_interval),
        reps=reps + 1,
        lapses_delta=0,
    )


def get_review_queue(
    course_id: str,
    limit: int = 20,
    *,
    learner_id: str = learner_context.LEGACY_LOCAL_LEARNER_ID,
    scope: str = "available",
    chapter_label: str | None = None,
) -> dict[str, Any]:
    """due cards: ReviewState.due_at <= now OR no ReviewState yet (new).
    Ordered by COALESCE(due_at, created_at) then created_at — a fully
    stable sort (never changes between two calls against the same data),
    so closing and reopening the queue resumes mid-queue for free: the
    cards already reviewed this session are no longer "due" (their new
    due_at moved into the future), and everything else keeps its same
    relative order.
    """
    session = get_session()
    try:
        now = utcnow()
        course_profile = learner_context.ensure_course_learning_profile(
            session, learner_id, course_id
        )
        order_key = func.coalesce(ReviewState.due_at, Card.created_at)

        query = (
            session.query(Card, ReviewState)
            .join(Section, Section.id == Card.section_id)
            .outerjoin(
                ReviewState,
                and_(
                    ReviewState.card_id == Card.id,
                    ReviewState.course_learning_profile_id == course_profile.id,
                ),
            )
            .filter(Card.course_id == course_id)
        )
        if chapter_label is not None:
            query = query.filter(Section.chapter_label == chapter_label)
        if scope == "available":
            query = query.filter((ReviewState.card_id.is_(None)) | (ReviewState.due_at <= now))
        elif scope == "needs_attention":
            query = query.filter(ReviewState.last_grade == AGAIN)

        rows = (
            query.with_entities(Card, Section, ReviewState)
            .order_by(order_key.asc(), Card.created_at.asc(), Card.id.asc())
            .limit(limit)
            .all()
        )

        cards = [
            {
                "id": card.id,
                "section_id": card.section_id,
                "chapter_label": section.chapter_label,
                "section_title": section.title,
                "front_md": card.front_md,
                "back_md": card.back_md,
                "due_at": review_state.due_at if review_state else None,
                "is_new": review_state is None,
                "is_due": bool(review_state and ensure_utc(review_state.due_at) <= now),
                "last_grade": review_state.last_grade if review_state else None,
                # Same bootstrap values grade_card() uses for a card with no
                # ReviewState yet (see below) — lets a caller run
                # schedule_next-equivalent math for a preview without a
                # second lookup.
                "interval_days": review_state.interval_days if review_state else 0.0,
                "ease": review_state.ease if review_state else DEFAULT_EASE,
                "reps": review_state.reps if review_state else 0,
            }
            for card, section, review_state in rows
        ]

        counts = get_review_availability(session, course_id, learner_id, now=now)
        return {
            "cards": cards,
            "due": counts.overdue_count,
            "new": counts.new_count,
            "total": counts.total_count,
            "overdue_count": counts.overdue_count,
            "new_count": counts.new_count,
            "available_count": counts.available_count,
            "total_count": counts.total_count,
        }
    finally:
        session.close()


def grade_card(
    card_id: str,
    grade: int,
    elapsed_ms: int | None = None,
    *,
    learner_id: str = learner_context.LEGACY_LOCAL_LEARNER_ID,
) -> dict[str, Any] | None:
    session = get_session()
    try:
        card = session.get(Card, card_id)
        if card is None:
            return None

        course_profile = learner_context.ensure_course_learning_profile(
            session, learner_id, card.course_id
        )

        review_state = session.get(ReviewState, (course_profile.id, card_id))
        if review_state is None:
            current_interval, current_ease, current_reps = 0.0, DEFAULT_EASE, 0
        else:
            current_interval = review_state.interval_days
            current_ease = review_state.ease
            current_reps = review_state.reps

        result = schedule_next(grade, interval_days=current_interval, ease=current_ease, reps=current_reps)

        if review_state is None:
            review_state = ReviewState(
                course_learning_profile_id=course_profile.id,
                card_id=card_id,
                course_id=card.course_id,
                due_at=result.due_at,
                interval_days=result.interval_days,
                ease=result.ease,
                reps=result.reps,
                lapses=result.lapses_delta,
                last_grade=grade,
            )
            session.add(review_state)
        else:
            review_state.due_at = result.due_at
            review_state.interval_days = result.interval_days
            review_state.ease = result.ease
            review_state.reps = result.reps
            review_state.lapses += result.lapses_delta
            review_state.last_grade = grade

        review_log = ReviewLog(
            course_learning_profile_id=course_profile.id,
            card_id=card_id,
            course_id=card.course_id,
            graded_at=utcnow(),
            grade=grade,
            elapsed_ms=elapsed_ms,
        )
        session.add(review_log)
        session.flush()
        evidence_item = evidence_service.find_item(
            session, item_type="flashcard", source_record_id=card.id
        )
        if evidence_item is None:
            evidence_item = evidence_items_service.snapshot_item(
                session,
                course_id=card.course_id,
                item_type="flashcard",
                source_record_id=card.id,
                source_index=-1,
                content={"front": card.front_md, "back": card.back_md},
                source_ref=card.section_id,
                prompt_version=card.prompt_version,
                model=None,
            )
        evidence_service.record_event(
            session,
            course_learning_profile_id=course_profile.id,
            evidence_item=evidence_item,
            channel="review",
            normalized_outcome=max(0.0, min(1.0, (grade - AGAIN) / (EASY - AGAIN))),
            raw_result={"grade": grade, "interval_days": result.interval_days},
            source_event_key=f"review_log:{review_log.id}",
            event_at=review_log.graded_at,
            elapsed_ms=elapsed_ms,
        )
        session.commit()

        counts = get_review_availability(session, card.course_id, learner_id, now=utcnow())
        return {"next_due_at": result.due_at, "remaining_due": counts.available_count}
    finally:
        session.close()


def get_review_summary(
    *, learner_id: str = learner_context.LEGACY_LOCAL_LEARNER_ID
) -> dict[str, Any]:
    session = get_session()
    try:
        now = utcnow()
        courses = session.query(Course).all()

        per_course = []
        due_total = 0
        course_profile_ids: list[str] = []
        for course in courses:
            course_profile = learner_context.ensure_course_learning_profile(
                session, learner_id, course.id
            )
            course_profile_ids.append(course_profile.id)
            counts = get_review_availability(session, course.id, learner_id, now=now)
            per_course.append(
                {
                    "course_id": course.id,
                    "title": course.title,
                    "due_count": counts.overdue_count,
                    "overdue_count": counts.overdue_count,
                    "new_count": counts.new_count,
                    "available_count": counts.available_count,
                    "total_count": counts.total_count,
                }
            )
            due_total += counts.overdue_count

        seven_days_ago = now - timedelta(days=7)
        grades_last_7d = (
            session.query(ReviewLog)
            .filter(
                ReviewLog.course_learning_profile_id.in_(course_profile_ids),
                ReviewLog.graded_at >= seven_days_ago,
            )
            .count()
            if course_profile_ids
            else 0
        )
        daily_throughput = grades_last_7d / 7.0

        backlog_warning = due_total > 2 * daily_throughput and due_total > 20

        return {
            "courses": per_course,
            "due_total": due_total,
            "daily_throughput": daily_throughput,
            "backlog_warning": backlog_warning,
        }
    finally:
        session.close()
