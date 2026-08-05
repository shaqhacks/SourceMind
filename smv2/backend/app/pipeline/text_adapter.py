from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.identity import content_hash_for, normalize_text
from app.pipeline.import_adapters import NormalizedSection, NormalizedSourceDocument
from app.pipeline.source_locators import HeadingLocator

TEXT_FORMAT_NAME = "text"
TEXT_MEDIA_TYPE = "text/plain"
TEXT_EXTRACTOR_VERSION = "text-stdlib-v1"


def looks_like_text_bytes(sample: bytes) -> bool:
    if not sample or b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def filename_heading(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or "Document"


def extract_text_document(path: Path, *, asset_id: str | None, filename: str) -> NormalizedSourceDocument:
    text = normalize_text(path.read_text(encoding="utf-8"))
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    base_title = filename_heading(filename)
    sections: list[NormalizedSection] = []
    for index, paragraph in enumerate(paragraphs, start=1):
        title = f"{base_title} - Paragraph {index}"
        body_md = normalize_text(paragraph)
        sections.append(
            NormalizedSection(
                stable_section_id=None,
                title=title,
                body_md=body_md,
                content_hash=content_hash_for(body_md),
                source_locator=HeadingLocator(
                    asset_id=asset_id,
                    heading_path=[base_title, f"Paragraph {index}"],
                ),
                chapter_label=None,
                asset_id=asset_id,
                source_format=TEXT_FORMAT_NAME,
                pages=[(0, body_md)],
            )
        )

    return NormalizedSourceDocument(
        metadata={"page_count": 1, "total_chars": len(text)},
        sections=sections,
        warnings=[],
        failures=[],
        extractor_name="text-stdlib",
        extractor_version=TEXT_EXTRACTOR_VERSION,
        source_format=TEXT_FORMAT_NAME,
    )


class TextDocumentAdapter:
    format_name = TEXT_FORMAT_NAME
    format_version = "1"
    media_type = TEXT_MEDIA_TYPE

    def sniff(self, asset: Any) -> bool:
        try:
            return looks_like_text_bytes(Path(asset.stored_path).read_bytes()[:4096])
        except OSError:
            return False

    def extract(self, asset: Any) -> NormalizedSourceDocument:
        return extract_text_document(Path(asset.stored_path), asset_id=asset.id, filename=asset.filename)
