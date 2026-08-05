from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.config import pages_per_window
from app.config import skip_front_matter as _skip_front_matter_enabled
from app.db.identity import content_hash_for, normalize_text
from app.pipeline.extract import (
    extract_heading_candidates,
    extract_markdown_pages_in_batches,
    get_toc,
    open_pdf,
    pdf_extractor_version,
    rewrite_image_refs_to_api_path,
)
from app.pipeline.ingest_paths import images_dir_for_course
from app.pipeline.outline_detect import (
    assign_chapter_labels,
    classify_section_kind,
    detect_sections,
    front_matter_bookmark_titles,
    toc_shaped_chapter_cover_mask,
)
from app.pipeline.source_locators import PdfPageLocator, SourceLocator

PDF_FORMAT_NAME = "pdf"
PDF_MEDIA_TYPE = "application/pdf"
PDF_MAGIC = b"%PDF-"
MAGIC_SNIFF_WINDOW = 1024


class UnsupportedSourceFormatError(Exception):
    pass


class DocumentAdapter(Protocol):
    format_name: str
    format_version: str
    media_type: str

    def sniff(self, asset: Any) -> bool: ...

    def extract(self, asset: Any) -> NormalizedSourceDocument: ...


@dataclass
class NormalizedSection:
    stable_section_id: str | None
    title: str
    body_md: str
    content_hash: str
    source_locator: SourceLocator
    chapter_label: str | None
    asset_id: str | None
    source_format: str
    page_start: int | None = None
    page_end: int | None = None
    kind: str = "content"
    pages: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class NormalizedSourceDocument:
    metadata: dict[str, Any]
    sections: list[NormalizedSection]
    warnings: list[str]
    failures: list[str]
    extractor_name: str
    extractor_version: str
    source_format: str


def sniff_pdf_path(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return PDF_MAGIC in fh.read(MAGIC_SNIFF_WINDOW)
    except OSError:
        return False


class PdfDocumentAdapter:
    format_name = PDF_FORMAT_NAME
    format_version = "1"
    media_type = PDF_MEDIA_TYPE

    def __init__(
        self,
        *,
        window: int | None = None,
        skip_front_matter: bool | None = None,
        on_batch: Callable[[int, int], None] | None = None,
    ) -> None:
        self._window = window
        self._skip_front_matter = skip_front_matter
        self._on_batch = on_batch

    def sniff(self, asset: Any) -> bool:
        return sniff_pdf_path(Path(asset.stored_path))

    def extract(self, asset: Any) -> NormalizedSourceDocument:
        pdf_path = Path(asset.stored_path)
        doc = open_pdf(pdf_path)
        try:
            toc = get_toc(doc)
            heading_candidates = extract_heading_candidates(doc)
            pages = extract_markdown_pages_in_batches(
                doc,
                batch_pages=20,
                on_batch=self._on_batch,
                image_dir=images_dir_for_course(asset.course_id),
                image_filename=asset.id,
            )
            page_count = doc.page_count
        finally:
            doc.close()

        window = self._window if self._window is not None else pages_per_window()
        skip_fm = (
            self._skip_front_matter
            if self._skip_front_matter is not None
            else _skip_front_matter_enabled()
        )
        bounds_list = detect_sections(
            toc,
            len(pages),
            window,
            pages=pages,
            heading_candidates=heading_candidates,
            skip_front_matter=skip_fm,
        )
        warnings: list[str] = []
        if skip_fm:
            warnings.extend(f"skipped front matter: {title}" for title in front_matter_bookmark_titles(toc))

        asset_titles = [bounds.title for bounds in bounds_list]
        chapter_labels = assign_chapter_labels(asset_titles)
        cover_mask = toc_shaped_chapter_cover_mask(bounds_list, pages, skip_front_matter=skip_fm)
        warnings.extend(
            f"skipped chapter cover page: {bounds.title}"
            for bounds, keep in zip(bounds_list, cover_mask)
            if not keep
        )
        bounds_list = [bounds for bounds, keep in zip(bounds_list, cover_mask) if keep]
        chapter_labels = [label for label, keep in zip(chapter_labels, cover_mask) if keep]

        sections: list[NormalizedSection] = []
        for idx, bounds in enumerate(bounds_list):
            page_slice = [(p, pages[p]) for p in range(bounds.page_start, bounds.page_end + 1)]
            body_md = "\n\n".join(text for _, text in page_slice if text and text.strip())
            body_md = rewrite_image_refs_to_api_path(body_md, asset.course_id)
            normalized = normalize_text(body_md)
            sections.append(
                NormalizedSection(
                    stable_section_id=None,
                    title=bounds.title,
                    body_md=normalized,
                    content_hash=content_hash_for(normalized),
                    source_locator=PdfPageLocator(
                        asset_id=asset.id,
                        page_start=bounds.page_start,
                        page_end=bounds.page_end,
                    ),
                    chapter_label=chapter_labels[idx],
                    asset_id=asset.id,
                    source_format=self.format_name,
                    page_start=bounds.page_start,
                    page_end=bounds.page_end,
                    kind=classify_section_kind(bounds.title),
                    pages=page_slice,
                )
            )

        return NormalizedSourceDocument(
            metadata={
                "page_count": page_count,
                "total_chars": sum(len(page) for page in pages),
                "toc": toc,
            },
            sections=sections,
            warnings=warnings,
            failures=[],
            extractor_name="pymupdf4llm",
            extractor_version=pdf_extractor_version(),
            source_format=self.format_name,
        )


def supported_adapters() -> list[DocumentAdapter]:
    return [PdfDocumentAdapter()]


def choose_document_adapter(
    asset: Any, *, adapters: list[DocumentAdapter] | None = None
) -> DocumentAdapter:
    for adapter in adapters if adapters is not None else supported_adapters():
        if adapter.sniff(asset):
            return adapter
    raise UnsupportedSourceFormatError(f"unsupported source format for asset {asset.id!r}")
