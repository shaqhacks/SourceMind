"""PyMuPDF-based PDF text and image extraction."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    image_paths: list[str] = field(default_factory=list)


def derive_title_from_pdf(pdf_path: Path, fallback_name: str = "") -> str:
    """Derive a human-readable course title from a PDF.

    Prefers the PDF's embedded metadata title; falls back to a prettified
    filename stem; finally returns 'Untitled Course'. Never raises.
    """
    meta_title = ""
    try:
        doc = fitz.open(str(pdf_path))
        try:
            meta_title = ((doc.metadata or {}).get("title") or "").strip()
        finally:
            doc.close()
    except Exception:
        meta_title = ""
    if meta_title:
        return meta_title
    stem = Path(fallback_name or str(pdf_path)).stem
    pretty = stem.replace("_", " ").replace("-", " ").strip()
    return pretty or "Untitled Course"


def extract_toc(pdf_path: Path) -> list[tuple[int, str, int]]:
    """Return the PDF's embedded table of contents (bookmarks).

    Each entry is ``(level, title, page_index)`` where ``level`` starts at 1 and
    ``page_index`` is 0-based. Returns an empty list if the PDF has no TOC or
    cannot be read. Never raises.
    """
    try:
        doc = fitz.open(str(pdf_path))
        try:
            raw = doc.get_toc(simple=True) or []
        finally:
            doc.close()
    except Exception:
        return []
    entries: list[tuple[int, str, int]] = []
    for item in raw:
        try:
            level, title, page = int(item[0]), str(item[1]), int(item[2])
        except (TypeError, ValueError, IndexError):
            continue
        # get_toc pages are 1-based; convert to 0-based, clamp at 0.
        entries.append((level, title, max(0, page - 1)))
    return entries


def extract_pdf(pdf_path: Path, assets_dir: Path) -> list[ExtractedPage]:
    """Extract text and embedded images from every page of a PDF.

    Args:
        pdf_path: Path to the source PDF file.
        assets_dir: Directory where extracted images are saved (created if absent).

    Returns:
        One ExtractedPage per page, in page order.
    """
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    pages: list[ExtractedPage] = []

    try:
        for i, page in enumerate(doc):
            text = page.get_text("text")

            image_paths: list[str] = []
            for img_tuple in page.get_images(full=True):
                xref = img_tuple[0]
                pix = fitz.Pixmap(doc, xref)

                # Convert CMYK or pixmaps with alpha to plain RGB
                if pix.n - pix.alpha >= 4 or pix.alpha:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                out_path = assets_dir / f"page{i}_img{xref}.png"
                pix.save(str(out_path))
                image_paths.append(str(out_path))

            pages.append(ExtractedPage(
                page_number=i,
                text=text,
                image_paths=image_paths,
            ))
    finally:
        doc.close()

    return pages
