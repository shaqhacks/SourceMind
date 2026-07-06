"""Chapter grouping: sections + test_attempts grouped by chapter_label
(ADR-017). Business logic for list_chapters — the router only does an
existence check and delegates here.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Section, TestAttempt


def get_chapters(course_id: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        sections = (
            session.query(Section)
            .filter(Section.course_id == course_id)
            .order_by(Section.order_index)
            .all()
        )

        groups: dict[str | None, dict[str, Any]] = {}
        for s in sections:
            group = groups.setdefault(
                s.chapter_label,
                {
                    "chapter_label": s.chapter_label,
                    "section_ids": [],
                    "practice_section_ids": [],
                    "answers_section_ids": [],
                },
            )
            if s.kind == "practice":
                group["practice_section_ids"].append(s.id)
            elif s.kind == "answers":
                group["answers_section_ids"].append(s.id)
            else:
                group["section_ids"].append(s.id)

        attempts = (
            session.query(TestAttempt)
            .filter(TestAttempt.course_id == course_id)
            .order_by(TestAttempt.created_at.asc())
            .all()
        )
        stats_by_label: dict[str | None, dict[str, Any]] = {}
        for a in attempts:
            stats = stats_by_label.setdefault(a.chapter_label, {"attempts": 0, "graded_scores": []})
            stats["attempts"] += 1
            if a.score is not None:
                stats["graded_scores"].append(a.score)

        result = []
        for label, group in groups.items():
            stats = stats_by_label.get(label)
            test_stats = None
            if stats is not None:
                graded_scores = stats["graded_scores"]
                test_stats = {
                    "attempts": stats["attempts"],
                    "best_score": max(graded_scores) if graded_scores else None,
                    # attempts were queried ordered by created_at ASC, so the
                    # last graded score in this list is the most recent one.
                    "latest_score": graded_scores[-1] if graded_scores else None,
                }
            group["test_stats"] = test_stats
            result.append(group)

        # NULL-labeled ("Front matter", labeled client-side) group first;
        # everything else keeps the order it was first encountered in
        # (i.e. course order_index order) — sort is stable, so this single
        # key only ever moves the None group to the front.
        result.sort(key=lambda g: g["chapter_label"] is not None)
        return result
    finally:
        session.close()
