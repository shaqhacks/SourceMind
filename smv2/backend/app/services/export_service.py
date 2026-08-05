"""Build a course export as a zip: outline.md (table of contents), one
order-prefixed .md per section, one lessons/NN-title.lesson.md per section
with a ready lesson, manifest.json (course meta + section ids/hashes/
extractor version/lesson metadata), and the original PDFs under assets/.

Lessons are paid-for, generated content — the brief's "the reader's content
must never be hostage to the app" applies to them just as much as to the
source text, so they must not be silently absent from the export.

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
from app.pipeline.source_locators import locator_export_label
from app.services import highlights_service, notes_service

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_UNSAFE_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_WINDOWS_RESERVED_BASENAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
# Exports over this size spill from memory to a temp file automatically.
_SPOOL_MAX_BYTES = 10 * 1024 * 1024


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug or "section"


def _section_filename(section: Section, width: int) -> str:
    return f"{section.order_index:0{width}d}-{_slugify(section.title)}.md"


def _lesson_filename(section: Section, width: int) -> str:
    return f"lessons/{section.order_index:0{width}d}-{_slugify(section.title)}.lesson.md"


def _extension_for_source(source_format: str | None, media_type: str | None) -> str:
    normalized_format = (source_format or "").lower()
    normalized_media = (media_type or "").lower()
    if normalized_format == "markdown" or normalized_media in {"text/markdown", "text/x-markdown"}:
        return ".md"
    if normalized_format == "html" or normalized_media == "text/html":
        return ".html"
    if normalized_format in {"text", "plain_text"} or normalized_media == "text/plain":
        return ".txt"
    if normalized_format == "pdf" or normalized_media == "application/pdf":
        return ".pdf"
    return ".bin"


def _sanitize_asset_filename(asset: Asset) -> str:
    original_name = Path(asset.filename or "asset").name
    cleaned = _UNSAFE_FILENAME_CHARS_RE.sub("-", original_name)
    if "." in cleaned:
        stem, current_ext = cleaned.rsplit(".", 1)
        current_ext = f".{current_ext.lower()}" if current_ext.strip(" .-") else ""
    else:
        stem, current_ext = cleaned, ""
    stem = stem.strip(" .-") or "asset"
    if stem.lower() in _WINDOWS_RESERVED_BASENAMES:
        stem = f"{stem}-source"
    expected_ext = _extension_for_source(asset.source_format, asset.media_type)
    return f"{stem}{current_ext if current_ext == expected_ext else expected_ext}"


def _asset_export_names(assets: list[Asset]) -> dict[str, str]:
    used: set[str] = set()
    export_names: dict[str, str] = {}
    for asset in assets:
        sanitized = _sanitize_asset_filename(asset)
        stem, ext = Path(sanitized).stem.rstrip(" .-") or "asset", Path(sanitized).suffix
        candidate = sanitized
        suffix = 2
        while candidate.lower() in used:
            candidate = f"{stem}-{suffix}{ext}"
            suffix += 1
        used.add(candidate.lower())
        export_names[asset.id] = f"assets/{candidate}"
    return export_names


def _has_ready_lesson(section: Section) -> bool:
    return section.lesson_status == "ready" and bool(section.lesson_md)


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
        assets = (
            session.query(Asset)
            .filter(Asset.course_id == course_id)
            .order_by(Asset.created_at.asc(), Asset.id.asc())
            .all()
        )
        asset_export_names = _asset_export_names(assets)
        width = len(str(max(len(sections) - 1, 0))) or 1

        spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_BYTES, mode="w+b")  # noqa: SIM115
        with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as zf:
            outline_lines = [f"# {course.title}", ""]
            for s in sections:
                outline_lines.append(f"- [{s.title}]({_section_filename(s, width)})")
            zf.writestr("outline.md", "\n".join(outline_lines) + "\n")

            manifest = {
                "course": {"id": course.id, "title": course.title, "status": course.status},
                "assets": [
                    {
                        "id": asset.id,
                        "filename": asset.filename,
                        "file": asset_export_names[asset.id],
                        "source_format": asset.source_format,
                        "media_type": asset.media_type,
                        "size_bytes": asset.size_bytes,
                        "sha256": asset.sha256,
                    }
                    for asset in assets
                ],
                "sections": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "order_index": s.order_index,
                        "content_hash": s.content_hash,
                        "extractor_version": s.extractor_version,
                        "source_format": s.source_format,
                        "source_locator": s.source_locator,
                        "source_label": locator_export_label(s.source_locator),
                        "lesson": (
                            {
                                "status": s.lesson_status,
                                "model": s.lesson_model,
                                "prompt_version": s.lesson_prompt_version,
                                "file": _lesson_filename(s, width),
                            }
                            if _has_ready_lesson(s)
                            else None
                        ),
                    }
                    for s in sections
                ],
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

            # User annotations travel with the export too — their own work must
            # not be hostage to the app. Sourced from highlights_service (never
            # a raw model re-query) so page stays 1-based like the API.
            highlights_payload = {
                "schema_version": 1,
                "course_id": course.id,
                "highlights": highlights_service.list_highlights(course_id),
            }
            zf.writestr(
                "highlights.json",
                json.dumps(highlights_payload, indent=2, default=str),
            )

            # Same reasoning as highlights.json above: margin notes are the
            # user's own work and must travel with the export too. Sourced
            # from notes_service (never a raw model re-query) so page stays
            # 1-based like the API.
            notes_payload = {
                "schema_version": 1,
                "course_id": course.id,
                "notes": notes_service.list_notes(course_id),
            }
            zf.writestr(
                "notes.json",
                json.dumps(notes_payload, indent=2, default=str),
            )

            for s in sections:
                zf.writestr(_section_filename(s, width), s.body_md or "")

            for s in sections:
                if _has_ready_lesson(s):
                    front_matter = f"<!-- model: {s.lesson_model}; prompt_version: {s.lesson_prompt_version} -->\n\n"
                    zf.writestr(_lesson_filename(s, width), front_matter + s.lesson_md)

            for asset in assets:
                asset_path = Path(asset.stored_path)
                if asset_path.exists():
                    zf.write(asset_path, arcname=asset_export_names[asset.id])

        spool.seek(0)
        return spool, course.title
    finally:
        session.close()
