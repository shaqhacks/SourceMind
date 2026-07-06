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
import tempfile
from pathlib import Path

import fitz

from app.pipeline.extract import (
    extract_heading_candidates,
    extract_markdown_pages_in_batches,
    get_toc,
    open_pdf,
    rewrite_image_refs_to_api_path,
)
from app.pipeline.outline_detect import (
    assign_chapter_labels,
    classify_section_kind,
    detect_sections,
    toc_shaped_chapter_cover_mask,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "pdfs"
SNAPSHOTS_DIR = REPO_ROOT / "tests" / "snapshots"

_FIXED_DATE = "D:20250101000000Z"
_SNAPSHOT_FIXTURES = ("with_bookmarks", "no_bookmarks", "non_english", "headings_no_bookmarks", "images")
# Not a real course — snapshot generation has no DB/course context, just a
# fixed, obviously-a-placeholder id so the rewritten image refs are
# reproducible in the committed golden JSON.
_SNAPSHOT_COURSE_ID_PLACEHOLDER = "snapshot-course-id"


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


def _add_mixed_page(doc: fitz.Document, entries: list[tuple[str, float, bool]]) -> None:
    """Like _add_text_page, but each line has its own font size and bold
    flag — needed for headings_no_bookmarks.pdf, where chapter headings
    must be visibly larger/bolder than body text so the heading-detection
    tier's font-size signal has something real to key off (unlike every
    other fixture, which is uniform-size text throughout).
    """
    page = doc.new_page(width=612, height=792)  # US Letter
    y = 72
    for text, fontsize, bold in entries:
        fontname = "Helvetica-Bold" if bold else "Helvetica"
        if text:
            page.insert_text((72, y), text, fontsize=fontsize, fontname=fontname)
        y += fontsize + 6


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


def make_front_matter() -> Path:
    """Title page + copyright page (ISBN/©) + a bookmarked "Table of
    Contents" page with dotted page-number lines, then 2 real bookmarked
    chapters — exercises ADR-013's deterministic front-matter skipping on
    both the bookmark path (the ToC bookmark itself) and the page-window
    fallback path (the 3 leading junk pages, when bookmarks are ignored).
    """
    doc = fitz.open()
    _add_text_page(doc, ["Front Matter Fixture", "", "A Testing Handbook"])
    _add_text_page(
        doc,
        [
            "Copyright © 2025 Fixture Publishing",
            "All rights reserved.",
            "ISBN 978-0-000-00000-0",
        ],
    )
    _add_text_page(
        doc,
        [
            "Table of Contents",
            "Chapter 1: Real Content .......... 4",
            "Chapter 2: More Content .......... 6",
            "Appendix A .......... 7",
            "Appendix B .......... 8",
            "Index .......... 9",
        ],
    )
    _add_text_page(
        doc,
        [
            "Chapter 1: Real Content",
            "",
            "This is the real first chapter of the fixture book.",
            "It contains genuine educational content for testing.",
        ],
    )
    _add_text_page(
        doc,
        [
            "Chapter 1: Real Content (continued)",
            "",
            "More real content continues here for the fixture.",
        ],
    )
    _add_text_page(
        doc,
        [
            "Chapter 2: More Content",
            "",
            "This is the second real chapter.",
        ],
    )
    _add_text_page(
        doc,
        [
            "Chapter 2: More Content (continued)",
            "",
            "Additional real content for chapter two.",
        ],
    )
    doc.set_toc(
        [
            [1, "Table of Contents", 3],
            [1, "Chapter 1: Real Content", 4],
            [1, "Chapter 2: More Content", 6],
        ]
    )
    _set_fixed_metadata(doc, "Front Matter Fixture")
    out = FIXTURES_DIR / "front_matter.pdf"
    doc.save(str(out), no_new_id=1)
    doc.close()
    return out


_HEADING_FONT_SIZE = 20
_BODY_FONT_SIZE = 11


def make_headings_no_bookmarks() -> Path:
    """No embedded bookmarks at all — chapter boundaries are only signaled
    by large bold "Chapter N: Title" lines (ADR-015's heading-detection
    tier). 16 pages, 5 chapters plus a practice sheet and an answer key
    (ADR-017's section-kind/chapter-grouping classification):

    - Chapter 2's and Chapter 3's headings both land on the same page —
      exercises the same-page-collision rule (first heading claims the
      page; the second is bumped to start on the next page).
    - A large-font, otherwise heading-shaped line that ends in a period (a
      "pull-quote") — must be excluded by the trailing-punctuation rule
      despite its size.
    - "0.1 Practice - Foundations" (kind='practice') sits right after
      Chapter 1, so it's grouped under Chapter 1's label positionally.
    - "Answers - Chapter 1" (kind='answers') sits at the very end, after
      Chapter 4 — positionally it would inherit Chapter 4's label, but its
      own title names Chapter 1, which must win (the answer-key override).
    - Chapter 5's own cover page ("Chapter 5: Probability" + a dotted
      mini-ToC of its own sections/page numbers, 1 page) sits between
      Chapter 4 and the answer key (ADR-021's ToC-shaped-chapter-cover
      drop) — must be dropped from the outline entirely, while the
      ordinary lesson section right after it ("5.1 Basic Probability")
      still correctly inherits chapter_label="Chapter 5: Probability",
      proving labels survive being computed before the cover is dropped.
    - Every other line is ordinary body-size (11pt) prose, so the body-size
      histogram clearly picks 11pt as the modal size.
    """
    doc = fitz.open()

    _add_mixed_page(
        doc,
        [
            ("Chapter 1: Foundations", _HEADING_FONT_SIZE, True),
            ("", _BODY_FONT_SIZE, False),
            ("This chapter introduces the foundational ideas the rest of", _BODY_FONT_SIZE, False),
            ("the book builds on, in plain deterministic fixture prose.", _BODY_FONT_SIZE, False),
        ],
    )
    _add_text_page(
        doc,
        [
            "Foundations continue with more ordinary body text on this",
            "page, long enough to read as genuine prose rather than a",
            "heading or a table of contents entry of any kind.",
        ],
    )
    _add_mixed_page(
        doc,
        [
            ("More foundations body text lives on this page before the", _BODY_FONT_SIZE, False),
            ("large pull-quote below, which must NOT be detected as a", _BODY_FONT_SIZE, False),
            ("heading despite its size, because it ends in a period.", _BODY_FONT_SIZE, False),
            ("", _BODY_FONT_SIZE, False),
            ("Deterministic fixtures make regressions visible.", _HEADING_FONT_SIZE, True),
        ],
    )
    _add_mixed_page(
        doc,
        [
            ("0.1 Practice - Foundations", _HEADING_FONT_SIZE, True),
            ("", _BODY_FONT_SIZE, False),
            ("A short practice sheet reinforcing the ideas from this", _BODY_FONT_SIZE, False),
            ("chapter, in plain deterministic fixture prose.", _BODY_FONT_SIZE, False),
        ],
    )
    _add_text_page(
        doc,
        [
            "Foundations closes out here with one more ordinary",
            "paragraph of body text before chapter 2 begins on the",
            "next page.",
        ],
    )
    _add_mixed_page(
        doc,
        [
            ("Chapter 2: Structures", _HEADING_FONT_SIZE, True),
            ("A deliberately short chapter.", _BODY_FONT_SIZE, False),
            ("Chapter 3: Applications", _HEADING_FONT_SIZE, True),
            ("Applications begins immediately, sharing this same page", _BODY_FONT_SIZE, False),
            ("with the end of chapter 2 directly above it.", _BODY_FONT_SIZE, False),
        ],
    )
    _add_text_page(
        doc,
        [
            "Applications continues here with plain body text, long",
            "enough to read as genuine prose rather than a heading",
            "candidate of any kind.",
        ],
    )
    _add_text_page(
        doc,
        [
            "More applications body text on this page, still well",
            "under the font-size threshold that would make it look",
            "like a heading.",
        ],
    )
    _add_text_page(
        doc,
        [
            "Applications closes out here with one final ordinary",
            "paragraph before chapter 4 begins on the next page.",
        ],
    )
    _add_mixed_page(
        doc,
        [
            ("Chapter 4: Geometry", _HEADING_FONT_SIZE, True),
            ("", _BODY_FONT_SIZE, False),
            ("The final chapter walks through worked geometry problems", _BODY_FONT_SIZE, False),
            ("using plain deterministic prose, same as every chapter.", _BODY_FONT_SIZE, False),
        ],
    )
    _add_text_page(
        doc,
        [
            "Geometry continues here with more ordinary body text,",
            "long enough to read as genuine prose for this fixture.",
        ],
    )
    _add_text_page(
        doc,
        [
            "Still more geometry body text on this page before the",
            "fixture reaches its answer key.",
        ],
    )
    _add_mixed_page(
        doc,
        [
            ("Chapter 5: Probability", _HEADING_FONT_SIZE, True),
            ("", _BODY_FONT_SIZE, False),
            ("5.1 Basic Probability .......................... 14", _BODY_FONT_SIZE, False),
            ("5.2 Independent Events ......................... 15", _BODY_FONT_SIZE, False),
            ("5.3 Conditional Probability .................... 16", _BODY_FONT_SIZE, False),
            ("5.4 Expected Value ............................. 17", _BODY_FONT_SIZE, False),
            ("5.5 Chapter Summary ............................ 18", _BODY_FONT_SIZE, False),
        ],
    )
    _add_mixed_page(
        doc,
        [
            ("5.1 Basic Probability", _HEADING_FONT_SIZE, True),
            ("", _BODY_FONT_SIZE, False),
            ("Chapter 5's own lesson content begins here, in plain", _BODY_FONT_SIZE, False),
            ("deterministic fixture prose covering the topics the", _BODY_FONT_SIZE, False),
            ("cover page's table of contents just listed.", _BODY_FONT_SIZE, False),
        ],
    )
    _add_mixed_page(
        doc,
        [
            ("Answers - Chapter 1", _HEADING_FONT_SIZE, True),
            ("", _BODY_FONT_SIZE, False),
            ("A short answer key naming the chapter it belongs to,", _BODY_FONT_SIZE, False),
            ("even though it physically sits at the end of the book.", _BODY_FONT_SIZE, False),
        ],
    )
    _add_text_page(
        doc,
        [
            "The fixture closes out here with one last ordinary",
            "paragraph of deterministic body text.",
        ],
    )

    _set_fixed_metadata(doc, "Headings No Bookmarks Fixture")
    out = FIXTURES_DIR / "headings_no_bookmarks.pdf"
    doc.save(str(out), no_new_id=1)
    doc.close()
    return out


def make_images() -> Path:
    """A born-digital PDF with ONE embedded raster image (a solid-color
    square — deterministic pixel data, no randomness) and no bookmarks —
    exercises image extraction + markdown-ref rewriting during ingest
    (ADR-018). No chapter markers, so it falls back to the page-window
    outline path exactly like no_bookmarks.pdf; page 2 has no image of its
    own, confirming extraction doesn't affect image-free pages.
    """
    doc = fitz.open()
    _add_text_page(
        doc,
        [
            "Images Fixture",
            "",
            "This page has ordinary body text before the embedded",
            "raster image below, for testing deterministic image",
            "extraction and markdown-ref rewriting during ingest.",
        ],
    )
    page = doc[-1]
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
    pix.set_rect(pix.irect, (200, 30, 30))  # solid fixed color -- no randomness
    page.insert_image(fitz.Rect(72, 300, 272, 500), pixmap=pix)
    _add_text_page(
        doc,
        [
            "This second page has no image of its own, just ordinary",
            "body text, to confirm image extraction doesn't affect",
            "pages that have none.",
        ],
    )
    _set_fixed_metadata(doc, "Images Fixture")
    out = FIXTURES_DIR / "images.pdf"
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
    "front_matter": make_front_matter,
    "headings_no_bookmarks": make_headings_no_bookmarks,
    "images": make_images,
}


def _snapshot_for(pdf_path: Path) -> dict:
    doc = open_pdf(pdf_path)
    try:
        toc = get_toc(doc)
        heading_candidates = extract_heading_candidates(doc)
        total_pages = doc.page_count
        # Scratch dir, never committed: mirrors ingest.py's own image_dir/
        # image_filename usage so a fixture's golden snapshot reflects the
        # SAME rewritten-ref markdown a real ingest would produce, using a
        # fixed placeholder course_id (there's no real course/DB here).
        with tempfile.TemporaryDirectory() as scratch_dir:
            pages = extract_markdown_pages_in_batches(
                doc,
                batch_pages=max(total_pages, 1),
                image_dir=Path(scratch_dir),
                image_filename=pdf_path.stem,
            )
        pages = [rewrite_image_refs_to_api_path(p, _SNAPSHOT_COURSE_ID_PLACEHOLDER) for p in pages]
    finally:
        doc.close()

    sections = detect_sections(
        toc, total_pages, pages_per_window=12, pages=pages, heading_candidates=heading_candidates
    )
    chapter_labels = assign_chapter_labels([s.title for s in sections])

    # ADR-021: same ordering requirement as ingest.py — labels are computed
    # against the full, undropped section list above, THEN ToC-shaped
    # chapter covers are filtered out, using the identical mask for both
    # sections and chapter_labels so they never drift out of sync.
    cover_mask = toc_shaped_chapter_cover_mask(sections, pages)
    sections = [s for s, keep in zip(sections, cover_mask) if keep]
    chapter_labels = [lbl for lbl, keep in zip(chapter_labels, cover_mask) if keep]

    outline = {
        "section_count": len(sections),
        "sections": [
            {
                "title": s.title,
                "page_start": s.page_start,
                "page_end": s.page_end,
                "kind": classify_section_kind(s.title),
                "chapter_label": chapter_labels[i],
            }
            for i, s in enumerate(sections)
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
