"""Business logic for course creation/lookup/deletion. Routers only do
existence checks and delegate here.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Course, ProgressState, Section


def create_course(title: str) -> Course:
    session = get_session()
    try:
        course = Course(title=title, status="created")
        session.add(course)
        session.commit()
        return course
    finally:
        session.close()


def get_course(course_id: str) -> Course | None:
    session = get_session()
    try:
        return session.get(Course, course_id)
    finally:
        session.close()


def get_course_detail(course_id: str) -> dict[str, Any] | None:
    """Course row plus derived section_count/progress summary — used only by
    the course-detail endpoint. Returns a dict (not the ORM object) since
    section_count/progress aren't real Course columns.
    """
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            return None

        section_count = (
            session.query(Section).filter(Section.course_id == course_id).count()
        )
        progress = session.get(ProgressState, course_id)

        return {
            "id": course.id,
            "title": course.title,
            "status": course.status,
            "created_at": course.created_at,
            "updated_at": course.updated_at,
            "section_count": section_count,
            "progress": (
                {
                    "section_id": progress.section_id,
                    "scroll_pos": progress.scroll_pos,
                    "updated_at": progress.updated_at,
                }
                if progress is not None
                else None
            ),
        }
    finally:
        session.close()


def set_course_status(course_id: str, status: str) -> bool:
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            return False
        course.status = status
        session.commit()
        return True
    finally:
        session.close()


def list_courses(limit: int = 50) -> list[Course]:
    session = get_session()
    try:
        return (
            session.query(Course)
            .order_by(Course.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        session.close()


def delete_course(course_id: str) -> bool:
    """Delete a course and rely on ON DELETE CASCADE/SET NULL for everything
    that references it — a single session.delete() proves the FK wiring
    works end-to-end (see test_course_delete_cascade.py).
    """
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            return False
        session.delete(course)
        session.commit()
        return True
    finally:
        session.close()
