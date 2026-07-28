"""Business logic for course creation/lookup/deletion. Routers only do
existence checks and delegate here.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from typing import Any

from sqlalchemy import func

from app.config import data_dir
from app.db.engine import get_session
from app.db.models import Asset, Course, ProgressState, Section

logger = logging.getLogger(__name__)


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
        failed_asset_count = (
            session.query(Asset)
            .filter(Asset.course_id == course_id, Asset.status == "extract_failed")
            .count()
        )
        progress = session.get(ProgressState, course_id)

        return {
            "id": course.id,
            "title": course.title,
            "status": course.status,
            "created_at": course.created_at,
            "updated_at": course.updated_at,
            "section_count": section_count,
            "failed_asset_count": failed_asset_count,
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


def list_courses(limit: int = 50) -> list[dict[str, Any]]:
    """Course rows plus per-course section_count/failed_asset_count via one
    grouped query each — CourseOut's schema defaults (0) would otherwise
    serialize for every course in the listing (the detail endpoint computes
    these; the listing never did).
    """
    session = get_session()
    try:
        courses = (
            session.query(Course)
            .order_by(Course.created_at.desc())
            .limit(limit)
            .all()
        )
        course_ids = [c.id for c in courses]
        section_counts = dict(
            session.query(Section.course_id, func.count(Section.id))
            .filter(Section.course_id.in_(course_ids))
            .group_by(Section.course_id)
            .all()
        )
        failed_asset_counts = dict(
            session.query(Asset.course_id, func.count(Asset.id))
            .filter(Asset.course_id.in_(course_ids), Asset.status == "extract_failed")
            .group_by(Asset.course_id)
            .all()
        )
        return [
            {
                "id": c.id,
                "title": c.title,
                "status": c.status,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "section_count": section_counts.get(c.id, 0),
                "failed_asset_count": failed_asset_counts.get(c.id, 0),
            }
            for c in courses
        ]
    finally:
        session.close()


def delete_course(course_id: str) -> bool:
    """Delete a course and rely on ON DELETE CASCADE/SET NULL for everything
    that references it in the DB — a single session.delete() proves the FK
    wiring works end-to-end (see test_course_delete_cascade.py). The DB
    delete does NOT touch the filesystem, so the uploaded PDFs under
    data_dir()/assets/{course_id} are removed as a separate step after the
    DB commit succeeds — DB is the source of truth; a failure removing
    files is logged, not raised, so it never undoes an otherwise-successful
    delete.
    """
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            return False
        session.delete(course)
        session.commit()
    finally:
        session.close()

    _remove_course_asset_files(course_id)
    return True


def _remove_course_asset_files(course_id: str) -> None:
    try:
        # Defense in depth: only ever rmtree a path built from a validated
        # uuid, never straight from a caller-supplied string, even though
        # course_id only reaches here after matching a real Course row.
        uuid.UUID(course_id)
    except ValueError:
        logger.error("refusing to remove asset files for non-uuid course_id: %r", course_id)
        return

    assets_dir = data_dir() / "assets" / course_id
    try:
        shutil.rmtree(assets_dir)
    except FileNotFoundError:
        pass  # no assets were ever uploaded for this course — nothing to clean up
    except OSError:
        logger.exception("failed to remove asset files for deleted course %s", course_id)
