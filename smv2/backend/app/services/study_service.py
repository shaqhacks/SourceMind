"""Deterministic study-suggestion triage (ADR-022) — pure SQL + arithmetic,
no LLM involved. Feeds both GET /api/courses/{id}/study-next (dashboard)
and chat_service's learner-context injection (top-3 suggestions woven
into the chat prompt's closing line).

Four tiers, in priority order, each chapter suggested at most once (by
its HIGHEST-priority matching tier — a chapter already suggested by an
earlier tier is skipped by every later one):
  (a) chapters with a failed/low best test score
  (b) chapters with a large due-card backlog
  (c) the course has never been opened at all (no ProgressState row) —
      a single "start here" suggestion for the first chapter
  (d) chapters that haven't been touched in a while, weighted by how
      poorly they were last tested (Anki-priority-style formula)

Thresholds/weights below are this module's own interpretive choices
(the brief didn't pin down exact numbers) — documented here rather than
guessed silently, same convention app/services/srs_service.py's own
docstring already follows for its bootstrap-interval choices.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import (
    ProgressState,
    ensure_utc,
    utcnow,
)
from app.services.chapters_service import get_chapters
from app.services.learner_context import LEGACY_LOCAL_LEARNER_ID
from app.services.review_availability_service import get_review_availability

# A chapter's best graded score below this reads as "not mastered yet" —
# a C-/D-range cutoff, not a passing/failing line the owner specified.
_LOW_SCORE_THRESHOLD = 0.6

# Below this many due cards, a chapter's backlog isn't yet worth a
# dedicated suggestion on its own (it'll surface in the ordinary review
# queue regardless).
_MIN_DUE_CARDS_FOR_SUGGESTION = 5

# Tunable multiplier on the staleness-priority formula; kept at a neutral
# 1.0 baseline since there's no calibration data yet to justify another
# value.
_STALE_PRIORITY_WEIGHT = 1.0

# A chapter with no test attempt at all is neither "mastered" nor
# "failing" — split the difference rather than let an untested chapter
# get treated as either extreme by the staleness formula below.
_NEUTRAL_SCORE_NORM = 0.5


def study_next(
    course_id: str,
    limit: int = 3,
    learner_id: str = LEGACY_LOCAL_LEARNER_ID,
) -> list[dict[str, Any]]:
    session = get_session()
    try:
        now = utcnow()
        # Real chapters only — the None-labeled "front matter" group
        # (chapters_service's own client-side "Front matter" bucket) isn't
        # a chapter a learner can be meaningfully pointed at to study.
        chapters = [
            c
            for c in get_chapters(course_id, learner_id=learner_id)
            if c["chapter_label"] is not None
        ]

        suggested: set[str] = set()
        ordered: list[dict[str, Any]] = []

        # (a) failed/low best test score — worst score first.
        low_score = [
            (c, c["test_stats"]["best_score"])
            for c in chapters
            if c["test_stats"] is not None
            and c["test_stats"]["best_score"] is not None
            and c["test_stats"]["best_score"] < _LOW_SCORE_THRESHOLD
        ]
        low_score.sort(key=lambda pair: pair[1])
        for c, best_score in low_score:
            ordered.append(
                {
                    "chapter_label": c["chapter_label"],
                    "reason": "low_test_score",
                    "detail": {"best_score": best_score},
                }
            )
            suggested.add(c["chapter_label"])

        # (b) large due-card backlog — heaviest backlog first. Practice
        # sections are included (cards can live there too); answer-key
        # sections are excluded, same as every other generation-scoping
        # path in this codebase.
        due_candidates = []
        for c in chapters:
            if c["chapter_label"] in suggested:
                continue
            section_ids = c["section_ids"] + c["practice_section_ids"]
            availability = get_review_availability(
                session, course_id, learner_id, now=now, section_ids=section_ids
            )
            if availability.available_count >= _MIN_DUE_CARDS_FOR_SUGGESTION:
                due_candidates.append((c, availability))
        due_candidates.sort(key=lambda pair: -pair[1].available_count)
        for c, availability in due_candidates:
            reason = "due_cards" if availability.overdue_count else "new_cards"
            detail = {
                "overdue_count": availability.overdue_count,
                "new_count": availability.new_count,
                "available_count": availability.available_count,
                "total_count": availability.total_count,
            }
            if availability.overdue_count:
                detail["due_count"] = availability.overdue_count
            ordered.append(
                {"chapter_label": c["chapter_label"], "reason": reason, "detail": detail}
            )
            suggested.add(c["chapter_label"])

        # (c) course never opened at all — ProgressState is course-scoped
        # (one row, the current position), not per-chapter, so there's no
        # way to tell which OTHER chapters have been visited from it; when
        # it's entirely absent, every chapter is equally "unread" and
        # suggesting all of them isn't useful, so this is a single
        # "start here" suggestion for the first chapter in course order.
        progress = session.get(ProgressState, course_id)
        if progress is None:
            for c in chapters:
                if c["chapter_label"] not in suggested:
                    ordered.append({"chapter_label": c["chapter_label"], "reason": "unread", "detail": {}})
                    suggested.add(c["chapter_label"])
                    break

        # (d) stale — the course HAS been opened before, just not
        # recently, and this chapter wasn't already surfaced above.
        # priority = (1 - score_norm) * days_since * weight: a chapter
        # that scored poorly (or was never tested) contributes more
        # priority per day of neglect than one already mastered.
        if progress is not None:
            days_since = max(0, (now - ensure_utc(progress.updated_at)).days)
            if days_since > 0:
                stale_candidates = []
                for c in chapters:
                    if c["chapter_label"] in suggested:
                        continue
                    stats = c["test_stats"]
                    score_norm = (
                        stats["best_score"]
                        if stats is not None and stats["best_score"] is not None
                        else _NEUTRAL_SCORE_NORM
                    )
                    priority = (1 - score_norm) * days_since * _STALE_PRIORITY_WEIGHT
                    if priority > 0:
                        stale_candidates.append((c, priority, days_since))
                stale_candidates.sort(key=lambda triple: -triple[1])
                for c, _priority, ds in stale_candidates:
                    ordered.append(
                        {"chapter_label": c["chapter_label"], "reason": "stale", "detail": {"days_since": ds}}
                    )
                    suggested.add(c["chapter_label"])

        return ordered[:limit]
    finally:
        session.close()
