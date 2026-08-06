from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.db.identity import content_hash_for, normalize_text
from app.pipeline.import_adapters import NormalizedSection, NormalizedSourceDocument
from app.pipeline.source_locators import HeadingLocator

MARKDOWN_FORMAT_NAME = "markdown"
MARKDOWN_MEDIA_TYPE = "text/markdown"
MARKDOWN_EXTRACTOR_VERSION = "markdown-stdlib-v1"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def looks_like_markdown_text(text: str) -> bool:
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            return True
        if not in_fence and _HEADING_RE.match(line):
            return True
        if re.search(r"\[[^\]]+\]\([^)]+\)", line):
            return True
    return False


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _heading_title(line: str) -> str:
    match = _HEADING_RE.match(line)
    return match.group(2).strip() if match else "Document"


def _heading_indices_outside_fences(lines: list[str]) -> list[int]:
    heading_indices: list[int] = []
    fence_marker: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence_marker is None:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = None
            continue
        if fence_marker is None and _HEADING_RE.match(line):
            heading_indices.append(index)
    return heading_indices


def extract_markdown_document(path: Path, *, asset_id: str | None) -> NormalizedSourceDocument:
    text = _read_text(path)
    normalized_doc = normalize_text(text)
    lines = normalized_doc.splitlines()
    heading_indices = _heading_indices_outside_fences(lines)
    if not heading_indices:
        heading_indices = [0]

    sections: list[NormalizedSection] = []
    for section_index, start in enumerate(heading_indices):
        end = (
            heading_indices[section_index + 1]
            if section_index + 1 < len(heading_indices)
            else len(lines)
        )
        body_md = normalize_text("\n".join(lines[start:end]))
        if not body_md:
            continue
        title = _heading_title(lines[start]) if _HEADING_RE.match(lines[start]) else "Document"
        sections.append(
            NormalizedSection(
                stable_section_id=None,
                title=title,
                body_md=body_md,
                content_hash=content_hash_for(body_md),
                source_locator=HeadingLocator(asset_id=asset_id, heading_path=[title]),
                chapter_label=None,
                asset_id=asset_id,
                source_format=MARKDOWN_FORMAT_NAME,
                pages=[(0, body_md)],
            )
        )

    return NormalizedSourceDocument(
        metadata={"page_count": 1, "total_chars": len(normalized_doc)},
        sections=sections,
        warnings=[],
        failures=[],
        extractor_name="markdown-stdlib",
        extractor_version=MARKDOWN_EXTRACTOR_VERSION,
        source_format=MARKDOWN_FORMAT_NAME,
    )


class MarkdownDocumentAdapter:
    format_name = MARKDOWN_FORMAT_NAME
    format_version = "1"
    media_type = MARKDOWN_MEDIA_TYPE

    def sniff(self, asset: Any) -> bool:
        try:
            return looks_like_markdown_text(_read_text(Path(asset.stored_path)))
        except UnicodeDecodeError:
            return False

    def extract(self, asset: Any) -> NormalizedSourceDocument:
        return extract_markdown_document(Path(asset.stored_path), asset_id=asset.id)
