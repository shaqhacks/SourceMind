from __future__ import annotations

from pathlib import Path

from app.config import data_dir


def images_dir_for_course(course_id: str) -> Path:
    return data_dir() / "assets" / course_id / "images"
