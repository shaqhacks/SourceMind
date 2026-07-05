"""Build a course export as a zip: outline.md (table of contents), one
order-prefixed .md per section, manifest.json (course meta + section
ids/hashes/extractor version), and the original PDFs under assets/.

Framework-free — returns an open SpooledTemporaryFile (small exports stay
in memory, large ones spill to disk automatically) rather than raw bytes,
so the router can stream it instead of buffering the whole zip in RAM.
"""

from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path

from app.db.engine import get_session
from app.db.models import Asset, Course, Section

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Exports over this size spill from memory to a temp file automatically.
_SPOOL_MAX_BYTES = 10 * 1024 * 1024


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug or "section"


def _section_filename(section: Section, width: int) -> str:
    return f"{section.order_index:0{width}d}-{_slugify(section.title)}.md"


def build_export_zip(course_id: str) -> tuple[tempfile.SpooledTemporaryFile, str] | None:
    """Returns None if the course doesn't exist (router maps that to 404),
    otherwise (spool, course_title) — spool is seeked to 0 and ready to
    read; the caller is responsible for closing it once fully streamed.
    """
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            return None

        sections = (
            session.query(Section)
            .filter(Section.course_id == course_id)
            .order_by(Section.order_index)
            .all()
        )
        assets = session.query(Asset).filter(Asset.course_id == course_id).all()
        width = len(str(max(len(sections) - 1, 0))) or 1

        spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_BYTES, mode="w+b")
        with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as zf:
            outline_lines = [f"# {course.title}", ""]
            for s in sections:
                outline_lines.append(f"- [{s.title}]({_section_filename(s, width)})")
            zf.writestr("outline.md", "\n".join(outline_lines) + "\n")

            manifest = {
                "course": {"id": course.id, "title": course.title, "status": course.status},
                "sections": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "order_index": s.order_index,
                        "content_hash": s.content_hash,
                        "extractor_version": s.extractor_version,
                    }
                    for s in sections
                ],
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

            for s in sections:
                zf.writestr(_section_filename(s, width), s.body_md or "")

            for asset in assets:
                asset_path = Path(asset.stored_path)
                if asset_path.exists():
                    zf.write(asset_path, arcname=f"assets/{asset_path.name}")

        spool.seek(0)
        return spool, course.title
    finally:
        session.close()
