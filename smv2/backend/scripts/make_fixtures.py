#!/usr/bin/env python3
"""Generate the deterministic PDF fixture corpus + golden snapshots used by
the ingest pipeline tests.

Usage:
    python scripts/make_fixtures.py              # (re)generate the PDFs only
    python scripts/make_fixtures.py --snapshots  # also regenerate golden snapshots

Regenerate snapshots in the SAME PR as any extractor/outline-algorithm
change (an extractor_version bump) — a stale snapshot silently hides a real
extraction regression instead of catching it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz

from app.pipeline.extract import extract_markdown_pages, get_toc, open_pdf
from app.pipeline.outline_detect import detect_sections

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "pdfs"
SNAPSHOTS_DIR = REPO_ROOT / "tests" / "snapshots"

_FIXED_DATE = "D:20250101000000Z"
_SNAPSHOT_FIXTURES = ("with_bookmarks", "no_bookmarks", "non_english")


def _set_fixed_metadata(doc: fitz.Document, title: str) -> None:
    doc.set_metadata(
        {
            "title": title,
            "author": "SourceMind fixture generator",
            "subject": "",
            "keywords": "",
            "creator": "",
            "producer": "",
            "creationDate": _FIXED_DATE,
            "modDate": _FIXED_DATE,
        }
    )


def _add_text_page(doc: fitz.Document, lines: list[str], fontfile: str | None = None) -> None:
    page = doc.new_page(width=612, height=792)  # US Letter
    y = 72
    for line in lines:
        if fontfile:
            page.insert_text((72, y), line, fontsize=11, fontname="F0", fontfile=fontfile)
        else:
            page.insert_text((72, y), line, fontsize=11)
        y += 16


# Base14 fonts (PyMuPDF's default when no fontfile is given) are Latin-only,
# so Greek/Cyrillic text needs a real Unicode font embedded. insert_text()
# embeds the font's glyph outlines directly into the output PDF, so once
# generated the fixture is self-contained — this path only has to resolve
# once, at generation time, not every time the PDF is later read.
_UNICODE_FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]


def _find_unicode_fontfile() -> str:
    for candidate in _UNICODE_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise RuntimeError(
        "no Unicode-capable font found for the non_english fixture; add a "
        "candidate path to _UNICODE_FONT_CANDIDATES for this platform"
    )


def make_with_bookmarks() -> Path:
    doc = fitz.open()
    chapters = [
        ("Chapter 1: Foundations", 4),
        ("Chapter 2: Structures", 4),
        ("Chapter 3: Applications", 4),
    ]
    toc: list[list] = []
    page_index = 0
    for title, page_count in chapters:
        toc.append([1, title, page_index + 1])  # set_toc/get_toc pages are 1-based
        for _ in range(page_count):
            _add_text_page(
                doc,
                [
                    title,
                    f"Page {page_index + 1} of the fixture document.",
                    "",
                    "This is deterministic fixture text used for golden-snapshot",
                    "testing of the zero-LLM ingest pipeline. Lorem ipsum dolor",
                    "sit amet, consectetur adipiscing elit, sed do eiusmod tempor",
                    "incididunt ut labore et dolore magna aliqua.",
                ],
            )
            page_index += 1
    doc.set_toc(toc)
    _set_fixed_metadata(doc, "With Bookmarks Fixture")
    out = FIXTURES_DIR / "with_bookmarks.pdf"
    doc.save(str(out), no_new_id=1)
    doc.close()
    return out


def make_no_bookmarks() -> Path:
    doc = fitz.open()
    for i in range(10):
        _add_text_page(
            doc,
            [
                f"Prose page {i + 1}",
                "",
                "This document has no embedded table of contents, so the",
                "ingest pipeline must fall back to fixed page-window",
                "sectioning instead of bookmark-derived sections.",
            ],
        )
    _set_fixed_metadata(doc, "No Bookmarks Fixture")
    out = FIXTURES_DIR / "no_bookmarks.pdf"
    doc.save(str(out), no_new_id=1)
    doc.close()
    return out


def make_huge() -> Path:
    doc = fitz.open()
    for i in range(520):
        page = doc.new_page(width=200, height=200)
        page.insert_text((10, 20), f"Tiny page {i + 1}", fontsize=8)
    _set_fixed_metadata(doc, "Huge Fixture")
    out = FIXTURES_DIR / "huge.pdf"
    doc.save(str(out), no_new_id=1)
    doc.close()
    return out


def make_scanned() -> Path:
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page(width=400, height=500)
        # Drawn shapes simulate a scanned page: visual content, zero
        # extractable text.
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(20, 20, 380, 480))
        shape.draw_rect(fitz.Rect(60, 60, 340, 200))
        shape.draw_circle((200, 350), 80)
        shape.finish(color=(0, 0, 0), fill=(0.8, 0.8, 0.8), width=2)
        shape.commit()
    _set_fixed_metadata(doc, "Scanned Fixture")
    out = FIXTURES_DIR / "scanned.pdf"
    doc.save(str(out), no_new_id=1)
    doc.close()
    return out


def make_encrypted() -> Path:
    doc = fitz.open()
    _add_text_page(doc, ["This content is password protected."])
    _set_fixed_metadata(doc, "Encrypted Fixture")
    out = FIXTURES_DIR / "encrypted.pdf"
    doc.save(
        str(out),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="fixture-owner",
        user_pw="fixture-user",
        no_new_id=1,
    )
    doc.close()
    return out


def make_malformed() -> Path:
    """A valid header with a truncated/incomplete tail — a corrupt structure
    fitz refuses to open, exercising the extract_failed path.
    """
    doc = fitz.open()
    _add_text_page(doc, ["This PDF will be truncated after generation."])
    _set_fixed_metadata(doc, "Malformed Fixture")
    full_bytes = doc.tobytes(no_new_id=1)
    doc.close()
    out = FIXTURES_DIR / "malformed.pdf"
    out.write_bytes(full_bytes[: len(full_bytes) // 3])
    return out


def make_non_english() -> Path:
    """Unicode coverage via Greek + Cyrillic.

    PyMuPDF's Base14 default fonts are Latin-only (WinAnsiEncoding) and
    silently render unsupported glyphs as placeholder dots, so this fixture
    explicitly embeds a real Unicode font rather than relying on the default.
    """
    fontfile = _find_unicode_fontfile()
    doc = fitz.open()
    _add_text_page(
        doc,
        [
            "Κεφάλαιο 1: Εισαγωγή",  # Greek: "Chapter 1: Introduction"
            "",
            "Это тестовый текст на кириллице для проверки экстракции.",
        ],
        fontfile=fontfile,
    )
    _add_text_page(
        doc,
        [
            "Глава 2: Продолжение",  # Cyrillic: "Chapter 2: Continuation"
            "",
            "Ελληνικό κείμενο για δοκιμή εξαγωγής Unicode.",
        ],
        fontfile=fontfile,
    )
    _set_fixed_metadata(doc, "Non-English Fixture")
    out = FIXTURES_DIR / "non_english.pdf"
    doc.save(str(out), no_new_id=1)
    doc.close()
    return out


FIXTURE_BUILDERS = {
    "with_bookmarks": make_with_bookmarks,
    "no_bookmarks": make_no_bookmarks,
    "huge": make_huge,
    "scanned": make_scanned,
    "encrypted": make_encrypted,
    "malformed": make_malformed,
    "non_english": make_non_english,
}


def _snapshot_for(pdf_path: Path) -> dict:
    doc = open_pdf(pdf_path)
    try:
        toc = get_toc(doc)
        pages = extract_markdown_pages(doc)
        total_pages = doc.page_count
    finally:
        doc.close()

    sections = detect_sections(toc, total_pages, pages_per_window=12)
    outline = {
        "section_count": len(sections),
        "sections": [
            {"title": s.title, "page_start": s.page_start, "page_end": s.page_end}
            for s in sections
        ],
    }

    first_40_lines = {}
    for i, s in enumerate(sections):
        body = "\n\n".join(pages[p] for p in range(s.page_start, s.page_end + 1))
        first_40_lines[f"section_{i}"] = "\n".join(body.splitlines()[:40])

    return {"outline": outline, "first_40_lines": first_40_lines}


def generate_pdfs() -> dict[str, Path]:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    return {name: builder() for name, builder in FIXTURE_BUILDERS.items()}


def generate_snapshots(paths: dict[str, Path]) -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    for name in _SNAPSHOT_FIXTURES:
        snapshot = _snapshot_for(paths[name])
        out = SNAPSHOTS_DIR / f"{name}.json"
        out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", action="store_true", help="also regenerate golden snapshots")
    args = parser.parse_args(argv)

    paths = generate_pdfs()
    print(f"generated {len(paths)} fixture PDFs in {FIXTURES_DIR}")

    if args.snapshots:
        generate_snapshots(paths)
        print(f"regenerated snapshots in {SNAPSHOTS_DIR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
