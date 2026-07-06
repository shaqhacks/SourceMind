"""Reader endpoints: section listing/detail and per-course reading progress.

Page numbers are converted from the DB's 0-based storage to 1-based here —
this is the one place that conversion happens, so it never leaks into the
pipeline layer and never gets applied twice.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import ProgressState, Section, utcnow
from app.llm.prompts import load_prompt, parse_prompt_version


class InvalidSectionForCourseError(ValueError):
    pass


def to_display_page(page: int | None) -> int | None:
    return page + 1 if page is not None else None


def list_sections(course_id: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        sections = (
            session.query(Section)
            .filter(Section.course_id == course_id)
            .order_by(Section.order_index)
            .all()
        )
        result = []
        for s in sections:
            body = s.body_md or ""
            result.append(
                {
                    "id": s.id,
                    "title": s.title,
                    "order_index": s.order_index,
                    "asset_id": s.asset_id,
                    "page_start": to_display_page(s.page_start),
                    "page_end": to_display_page(s.page_end),
                    "lesson_status": s.lesson_status,
                    "has_content": bool(body.strip()),
                    "word_count": len(body.split()),
                    "kind": s.kind,
                    "chapter_label": s.chapter_label,
                }
            )
        return result
    finally:
        session.close()


def get_section(section_id: str) -> dict[str, Any] | None:
    session = get_session()
    try:
        s = session.get(Section, section_id)
        if s is None:
            return None
        _, current_prompt_version = load_prompt("lesson")
        # No lesson yet -> "stale" isn't a meaningful concept; only flag a
        # lesson generated under a prompt version older than the current
        # one. Compared numerically (parse_prompt_version), not as strings —
        # 'v10' < 'v9' lexicographically, which would silently misflag
        # staleness once a version reaches two digits.
        lesson_stale = bool(s.lesson_prompt_version) and parse_prompt_version(
            s.lesson_prompt_version
        ) < parse_prompt_version(current_prompt_version)
        return {
            "id": s.id,
            "course_id": s.course_id,
            "title": s.title,
            "order_index": s.order_index,
            "asset_id": s.asset_id,
            "page_start": to_display_page(s.page_start),
            "page_end": to_display_page(s.page_end),
            "body_md": s.body_md,
            "content_hash": s.content_hash,
            "lesson_md": s.lesson_md,
            "lesson_status": s.lesson_status,
            "lesson_stale": lesson_stale,
            "lesson_model": s.lesson_model,
            "lesson_prompt_version": s.lesson_prompt_version,
            "extractor_version": s.extractor_version,
            "kind": s.kind,
            "chapter_label": s.chapter_label,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
    finally:
        session.close()


def save_progress(course_id: str, section_id: str | None, scroll_pos: float) -> dict[str, Any]:
    session = get_session()
    try:
        if section_id is not None:
            section = session.get(Section, section_id)
            if section is None or section.course_id != course_id:
                raise InvalidSectionForCourseError(
                    f"section {section_id} does not belong to course {course_id}"
                )

        progress = session.get(ProgressState, course_id)
        if progress is None:
            progress = ProgressState(course_id=course_id, section_id=section_id, scroll_pos=scroll_pos)
            session.add(progress)
        else:
            progress.section_id = section_id
            progress.scroll_pos = scroll_pos
            progress.updated_at = utcnow()
        session.commit()
        return {
            "course_id": progress.course_id,
            "section_id": progress.section_id,
            "scroll_pos": progress.scroll_pos,
            "updated_at": progress.updated_at,
        }
    finally:
        session.close()


def get_progress(course_id: str) -> dict[str, Any]:
    session = get_session()
    try:
        progress = session.get(ProgressState, course_id)
        if progress is None:
            return {
                "course_id": course_id,
                "section_id": None,
                "scroll_pos": 0.0,
                "updated_at": None,
            }
        return {
            "course_id": progress.course_id,
            "section_id": progress.section_id,
            "scroll_pos": progress.scroll_pos,
            "updated_at": progress.updated_at,
        }
    finally:
        session.close()
