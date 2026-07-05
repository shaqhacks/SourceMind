"""Business logic for course creation/lookup/deletion. Routers only do
existence checks and delegate here.
"""

from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Course


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
