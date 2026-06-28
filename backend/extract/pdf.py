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
