"""ReviewState-backed spaced repetition using an SM-2-style algorithm.

Public API
----------
grade_card(session, course_id, section_id, card_index, correct, now=None) -> ReviewState
due_cards(session, course_id, now=None) -> list[ReviewState]
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from SourceMind.backend.db import models

# SM-2 defaults
_DEFAULT_EASE: float = 2.5
_MIN_EASE: float = 1.3
_EASE_CORRECT_NUDGE: float = 0.05
_EASE_WRONG_PENALTY: float = 0.2


def grade_card(
    session: Session,
    course_id: str,
    section_id: str,
    card_index: int,
    correct: bool,
    now: datetime | None = None,
) -> models.ReviewState:
    """Apply an SM-2-style update to the ReviewState for one flashcard.

    Find or create the row for (course_id, section_id, card_index), update
    ease / interval / reps / due_at, flush to the session, and return it.
    The caller's get_session() context manager commits.

    Parameters
    ----------
    session:    Active SQLAlchemy session (caller owns the transaction).
    course_id:  Course identifier.
    section_id: Section / chapter identifier within the course.
    card_index: Zero-based index of the card within the section.
    correct:    Whether the learner answered correctly.
    now:        Base datetime for due_at computation.  Defaults to UTC now.
                Pass a fixed value in tests for deterministic assertions.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Find or create row
    # ------------------------------------------------------------------
    row: models.ReviewState | None = (
        session.query(models.ReviewState)
        .filter_by(course_id=course_id, section_id=section_id, card_index=card_index)
        .first()
    )
    if row is None:
        row = models.ReviewState(
            course_id=course_id,
            section_id=section_id,
            card_index=card_index,
            ease=_DEFAULT_EASE,
            interval=0,
            reps=0,
            due_at="",
        )
        session.add(row)
        session.flush()  # assign PK so subsequent queries in this session find it

    # Resolve defaults for rows that pre-existed with NULL fields
    ease: float = row.ease if row.ease is not None else _DEFAULT_EASE
    interval: int = row.interval if row.interval is not None else 0
    reps: int = row.reps if row.reps is not None else 0

    # ------------------------------------------------------------------
    # SM-2-style update
    # ------------------------------------------------------------------
    if correct:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            # reps >= 3: grow by ease factor
            interval = round(interval * ease)
        ease = max(_MIN_EASE, ease + _EASE_CORRECT_NUDGE)
    else:
        reps = 0
        interval = 1
        ease = max(_MIN_EASE, ease - _EASE_WRONG_PENALTY)

    due_at = (now + timedelta(days=interval)).isoformat()

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    row.ease = ease
    row.interval = interval
    row.reps = reps
    row.due_at = due_at

    return row


def due_cards(
    session: Session,
    course_id: str,
    now: datetime | None = None,
) -> list[models.ReviewState]:
    """Return all ReviewState rows for *course_id* that are due at or before *now*.

    Rows with an empty ``due_at`` string are treated as immediately due.
    Results are ordered by ``due_at`` ascending (empty strings sort first).

    Parameters
    ----------
    session:   Active SQLAlchemy session.
    course_id: Course identifier.
    now:       Reference datetime.  Defaults to UTC now.
               Pass a fixed value in tests for deterministic behaviour.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure now is timezone-aware for comparison
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    rows: list[models.ReviewState] = (
        session.query(models.ReviewState)
        .filter_by(course_id=course_id)
        .all()
    )

    due: list[models.ReviewState] = []
    for row in rows:
        if not row.due_at:
            # Empty due_at → treat as immediately due
            due.append(row)
        else:
            try:
                due_dt = datetime.fromisoformat(row.due_at)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                if due_dt <= now:
                    due.append(row)
            except ValueError:
                # Unparseable date — treat as due to avoid hiding cards
                due.append(row)

    # Sort ascending: empty string ("") sorts before any ISO date string
    due.sort(key=lambda r: r.due_at or "")
    return due
