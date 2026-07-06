"""Serves images extracted from a course's source PDFs during ingest
(ADR-018). Images live at data_dir()/assets/{course_id}/images/, one
directory per course, wiped and regenerated wholesale on every re-ingest
(app/pipeline/ingest.py) and removed entirely on course delete (it's a
subdirectory of the course's assets dir, already covered by
courses_service._remove_course_asset_files' rmtree).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import data_dir

# Deliberately strict: no "/", no path separators of any kind, so a
# traversal attempt ("../../etc/passwd", "..%2F..") can never even reach
# the containment check below by matching this pattern in the first place.
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class InvalidImageFilenameError(ValueError):
    pass


class ImageNotFoundError(ValueError):
    pass


def images_dir(course_id: str) -> Path:
    return data_dir() / "assets" / course_id / "images"


def resolve_image_path(course_id: str, filename: str) -> Path:
    """Returns the absolute path to `filename` inside this course's images
    directory. Raises rather than ever returning a path outside it.

    Two independent layers on purpose: the allowlist regex rejects any
    filename containing a path separator outright, but a filename made
    entirely of dots (e.g. "..") would still pass that regex and, left
    unchecked, resolve to the PARENT of the images directory once joined
    and resolved — the explicit containment check below is what actually
    stops that case, not the regex alone.
    """
    if not _SAFE_FILENAME_RE.match(filename):
        raise InvalidImageFilenameError(f"invalid image filename: {filename!r}")

    base_dir = images_dir(course_id).resolve()
    candidate = (base_dir / filename).resolve()

    if candidate != base_dir and base_dir not in candidate.parents:
        raise InvalidImageFilenameError(f"resolved path escapes the images directory: {filename!r}")

    if not candidate.is_file():
        raise ImageNotFoundError(f"image not found: {filename!r}")

    return candidate
