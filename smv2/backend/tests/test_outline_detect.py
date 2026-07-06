from __future__ import annotations

from pathlib import Path

from app.pipeline.extract import extract_heading_candidates, extract_markdown_pages, get_toc, open_pdf
from app.pipeline.outline_detect import (
    detect_sections,
    first_content_page_index,
    front_matter_bookmark_titles,
    sections_from_headings,
    sections_from_page_windows,
    sections_from_toc,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"


def _detect_sections_for_fixture(name: str):
    doc = open_pdf(FIXTURES_DIR / name)
    try:
        toc = get_toc(doc)
        candidates = extract_heading_candidates(doc)
        pages = extract_markdown_pages(doc)
        total_pages = doc.page_count
    finally:
        doc.close()
    return detect_sections(toc, total_pages, 12, pages=pages, heading_candidates=candidates)


def test_sections_from_toc_uses_level_1_when_at_least_3_entries():
    toc = [
        (1, "Ch 1", 0),
        (1, "Ch 2", 5),
        (1, "Ch 3", 10),
        (2, "Ch 1.1", 1),  # nested — ignored since level 1 qualifies
    ]
    sections = sections_from_toc(toc, total_pages=15)
    assert [s.title for s in sections] == ["Ch 1", "Ch 2", "Ch 3"]
    assert sections[0].page_start == 0 and sections[0].page_end == 4
    assert sections[1].page_start == 5 and sections[1].page_end == 9
    assert sections[2].page_start == 10 and sections[2].page_end == 14


def test_sections_from_toc_falls_back_to_level_2_when_level_1_has_fewer_than_3():
    toc = [
        (1, "Part I", 0),
        (1, "Part II", 8),
        (2, "Ch 1", 0),
        (2, "Ch 2", 3),
        (2, "Ch 3", 8),
        (2, "Ch 4", 11),
    ]
    sections = sections_from_toc(toc, total_pages=16)
    assert [s.title for s in sections] == ["Ch 1", "Ch 2", "Ch 3", "Ch 4"]


def test_sections_from_toc_empty_when_no_entries():
    assert sections_from_toc([], total_pages=10) == []


def test_sections_from_toc_ignores_blank_titles():
    toc = [(1, "  ", 0), (1, "Real Chapter", 2), (1, "Another", 5), (1, "Third", 8)]
    sections = sections_from_toc(toc, total_pages=10)
    assert [s.title for s in sections] == ["Real Chapter", "Another", "Third"]


def test_sections_from_page_windows_splits_evenly():
    sections = sections_from_page_windows(total_pages=25, pages_per_window=12)
    assert len(sections) == 3
    assert (sections[0].page_start, sections[0].page_end) == (0, 11)
    assert (sections[1].page_start, sections[1].page_end) == (12, 23)
    assert (sections[2].page_start, sections[2].page_end) == (24, 24)
    assert sections[0].title == "Pages 1–12"


def test_sections_from_page_windows_empty_for_zero_pages():
    assert sections_from_page_windows(total_pages=0, pages_per_window=12) == []


def test_sections_from_page_windows_clamps_window_to_at_least_1():
    sections = sections_from_page_windows(total_pages=3, pages_per_window=0)
    assert len(sections) == 3


def test_detect_sections_uses_toc_when_enough_bookmarks():
    toc = [(1, "A", 0), (1, "B", 3), (1, "C", 6)]
    sections = detect_sections(toc, total_pages=9, pages_per_window=12)
    assert [s.title for s in sections] == ["A", "B", "C"]


def test_detect_sections_falls_back_when_fewer_than_2_toc_sections():
    toc = [(1, "Only One", 0)]
    sections = detect_sections(toc, total_pages=24, pages_per_window=12)
    assert len(sections) == 2
    assert sections[0].title == "Pages 1–12"


def test_detect_sections_falls_back_when_no_toc_at_all():
    sections = detect_sections([], total_pages=13, pages_per_window=12)
    assert len(sections) == 2


# --- ADR-013: bookmark-path front-matter denylist ---------------------------


def test_sections_from_toc_drops_denylisted_front_matter_titles():
    toc = [(1, "Table of Contents", 2), (1, "Chapter 1", 3), (1, "Chapter 2", 5)]
    sections = sections_from_toc(toc, total_pages=7)
    assert [s.title for s in sections] == ["Chapter 1", "Chapter 2"]
    # Content before the first surviving bookmark (the dropped ToC's own
    # pages included) is never covered by any section.
    assert sections[0].page_start == 3


def test_sections_from_toc_keeps_denylisted_titles_when_skip_front_matter_disabled():
    toc = [(1, "Table of Contents", 2), (1, "Chapter 1", 3), (1, "Chapter 2", 5)]
    sections = sections_from_toc(toc, total_pages=7, skip_front_matter=False)
    assert [s.title for s in sections] == ["Table of Contents", "Chapter 1", "Chapter 2"]


def test_sections_from_toc_denylist_is_case_insensitive_and_whitespace_tolerant():
    toc = [(1, "  copyright   page  ", 0), (1, "Chapter 1", 1), (1, "Chapter 2", 4)]
    sections = sections_from_toc(toc, total_pages=8)
    assert [s.title for s in sections] == ["Chapter 1", "Chapter 2"]


def test_sections_from_toc_does_not_drop_preface_foreword_introduction_or_index():
    toc = [
        (1, "Preface", 0),
        (1, "Foreword", 1),
        (1, "Introduction", 2),
        (1, "Chapter 1", 3),
        (1, "Index", 8),
    ]
    sections = sections_from_toc(toc, total_pages=10)
    assert [s.title for s in sections] == ["Preface", "Foreword", "Introduction", "Chapter 1", "Index"]


def test_front_matter_bookmark_titles_reports_only_denylisted_entries():
    toc = [
        (1, "Copyright", 0),
        (1, "Table Of Contents", 1),
        (1, "Chapter 1", 2),
        (1, "Chapter 2", 5),
    ]
    assert front_matter_bookmark_titles(toc) == ["Copyright", "Table Of Contents"]


def test_front_matter_bookmark_titles_empty_when_nothing_denylisted():
    toc = [(1, "Chapter 1", 0), (1, "Chapter 2", 4), (1, "Chapter 3", 8)]
    assert front_matter_bookmark_titles(toc) == []


# --- ADR-013: page-window-path leading front-matter page skip ---------------

_REAL_CONTENT_PAGE = (
    "This chapter contains genuine prose long enough to clear the near-empty "
    "threshold and read as real book content rather than a title or blurb page."
)
_TOC_SHAPED_PAGE = "\n".join(
    [
        "Table of Contents",
        "Intro .......... 1",
        "Chapter One .......... 4",
        "Chapter Two .......... 8",
        "Chapter Three .......... 12",
        "Appendix .......... 16",
    ]
)


def test_first_content_page_index_skips_copyright_signal_page():
    pages = ["Copyright 2025. All rights reserved. ISBN 000-0-000000-0-0.", _REAL_CONTENT_PAGE]
    assert first_content_page_index(pages) == 1


def test_first_content_page_index_skips_toc_shaped_page():
    pages = [_TOC_SHAPED_PAGE, _REAL_CONTENT_PAGE]
    assert first_content_page_index(pages) == 1


def test_first_content_page_index_skips_near_empty_page():
    pages = ["Title Page", _REAL_CONTENT_PAGE]
    assert first_content_page_index(pages) == 1


def test_first_content_page_index_stops_at_first_real_content_page():
    pages = ["Title Page", _REAL_CONTENT_PAGE, "Title Page"]
    assert first_content_page_index(pages) == 1


def test_first_content_page_index_zero_when_first_page_is_real_content():
    assert first_content_page_index([_REAL_CONTENT_PAGE, "Title Page"]) == 0


def test_first_content_page_index_returns_zero_when_scan_window_never_clears():
    # 11 near-empty pages: the scan window (first 10) never finds a content
    # page, so this returns 0 rather than guessing/consuming the whole scan
    # window — a false positive here would silently eat real content.
    pages = ["short"] * 11
    assert first_content_page_index(pages) == 0


def test_detect_sections_window_path_skips_leading_front_matter_pages():
    pages = ["Title Page", "Copyright 2025. All rights reserved.", _TOC_SHAPED_PAGE, _REAL_CONTENT_PAGE, _REAL_CONTENT_PAGE]
    sections = detect_sections([], total_pages=len(pages), pages_per_window=2, pages=pages)
    assert len(sections) == 1
    assert (sections[0].page_start, sections[0].page_end) == (3, 4)
    assert sections[0].title == "Pages 4–5"


def test_detect_sections_window_path_ignores_front_matter_when_disabled():
    pages = ["Title Page", _REAL_CONTENT_PAGE]
    sections = detect_sections(
        [], total_pages=len(pages), pages_per_window=12, pages=pages, skip_front_matter=False
    )
    assert sections[0].page_start == 0


def test_detect_sections_window_path_without_pages_never_skips():
    # No page text supplied at all (pages=None, the default) -> the
    # front-matter skip cannot run and windowing behaves exactly as before.
    sections = detect_sections([], total_pages=13, pages_per_window=12)
    assert sections[0].page_start == 0


# --- ADR-015: heading-detection middle tier ---------------------------------

_BODY = 11.0
_HEAD = 20.0


def _body_line(page: int, text: str = "Ordinary body prose long enough to pad out this page.") -> tuple:
    return (page, text, _BODY, False)


def test_sections_from_headings_detects_chapters_by_font_size():
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        _body_line(1),
        (2, "Chapter 2: Structures", _HEAD, True),
        _body_line(2),
        _body_line(3),
        (4, "Chapter 3: Applications", _HEAD, True),
        _body_line(4),
        _body_line(5),
    ]
    sections = sections_from_headings(candidates, total_pages=6)
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]
    assert (sections[0].page_start, sections[0].page_end) == (0, 1)
    assert (sections[1].page_start, sections[1].page_end) == (2, 3)
    assert (sections[2].page_start, sections[2].page_end) == (4, 5)


def test_sections_from_headings_excludes_line_ending_in_disqualifying_punctuation():
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        (1, "A large but non-heading pull-quote goes here.", _HEAD, True),  # ends in "."
        _body_line(1),
        (2, "Chapter 2: Structures", _HEAD, True),
        _body_line(2),
        (3, "Chapter 3: Applications", _HEAD, True),
        _body_line(3),
    ]
    sections = sections_from_headings(candidates, total_pages=4)
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]


def test_sections_from_headings_excludes_mostly_digit_lines():
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        (1, "123456", _HEAD, False),  # a large-font running-header page number
        _body_line(1),
        (2, "Chapter 2: Structures", _HEAD, True),
        _body_line(2),
        (3, "Chapter 3: Applications", _HEAD, True),
        _body_line(3),
    ]
    sections = sections_from_headings(candidates, total_pages=4)
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]


def test_sections_from_headings_excludes_lines_outside_length_bounds():
    too_short = "Hi"  # length 2, below the 3-char minimum
    too_long = "X" * 81  # 81 chars, above the 80-char maximum
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        (0, too_short, _HEAD, True),
        (0, too_long, _HEAD, True),
        _body_line(0),
        (1, "Chapter 2: Structures", _HEAD, True),
        _body_line(1),
        (2, "Chapter 3: Applications", _HEAD, True),
        _body_line(2),
    ]
    sections = sections_from_headings(candidates, total_pages=3)
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]


def test_sections_from_headings_boost_regex_qualifies_below_the_standard_multiplier():
    boosted_size = _BODY * 1.15  # between the 1.1x boost floor and the 1.25x standard floor
    candidates = [
        (0, "Chapter 1: Foundations", boosted_size, True),
        _body_line(0),
        (1, "Chapter 2: Structures", boosted_size, True),
        _body_line(1),
        (2, "Chapter 3: Applications", boosted_size, True),
        _body_line(2),
    ]
    sections = sections_from_headings(candidates, total_pages=3)
    assert len(sections) == 3  # only qualifies because of the "Chapter N" boost


def test_sections_from_headings_non_boosted_line_needs_the_standard_multiplier():
    boosted_size = _BODY * 1.15  # would qualify a "Chapter N"-shaped line, but not a plain one
    candidates = [
        (0, "Not A Chapter Marker At All", boosted_size, True),
        _body_line(0),
        (1, "Also Not A Chapter Marker", boosted_size, True),
        _body_line(1),
        (2, "Still Not One Either", boosted_size, True),
        _body_line(2),
    ]
    assert sections_from_headings(candidates, total_pages=3) == []


def test_sections_from_headings_single_oversized_title_fails_its_own_tier():
    """A single huge one-off title (e.g. a book's own cover-page title,
    stray oversized text) doesn't win as its OWN tier -- only 1 candidate,
    below _MIN_HEADING_SECTIONS -- so the tier with 3+ headings wins
    instead. The no-drop guard still surfaces the oversized title as the
    leading section's name (real content, not "Introduction") since it's
    the longest heading-candidate line sitting on the gap page.
    """
    candidates = [
        (0, "The Book Title Itself", 40.0, True),  # tier of 1 -- disqualified by count
        _body_line(0),
        (1, "Chapter 1: Foundations", _HEAD, True),
        _body_line(1),
        (2, "Chapter 2: Structures", _HEAD, True),
        _body_line(2),
        (3, "Chapter 3: Applications", _HEAD, True),
        _body_line(3),
    ]
    sections = sections_from_headings(candidates, total_pages=4)
    assert [s.title for s in sections] == [
        "The Book Title Itself",
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]
    assert (sections[0].page_start, sections[0].page_end) == (0, 0)


def test_sections_from_headings_same_page_collision_bumps_second_to_next_page():
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        (2, "Chapter 2: Structures", _HEAD, True),
        _body_line(2, "A deliberately short chapter."),
        (2, "Chapter 3: Applications", _HEAD, True),  # same page as Chapter 2's heading
        _body_line(2, "Applications begins immediately on the same page."),
        (5, "Chapter 4: Practice", _HEAD, True),
        _body_line(5),
    ]
    sections = sections_from_headings(candidates, total_pages=6)
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
        "Chapter 4: Practice",
    ]
    assert (sections[0].page_start, sections[0].page_end) == (0, 1)
    assert (sections[1].page_start, sections[1].page_end) == (2, 2)  # claims the shared page
    assert (sections[2].page_start, sections[2].page_end) == (3, 4)  # bumped to the next page
    assert (sections[3].page_start, sections[3].page_end) == (5, 5)


def test_sections_from_headings_returns_empty_when_fewer_than_3_qualify():
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        (1, "Chapter 2: Structures", _HEAD, True),
        _body_line(1),
    ]
    assert sections_from_headings(candidates, total_pages=2) == []


def test_sections_from_headings_returns_empty_when_coverage_below_60_percent():
    """3 qualifying headings, but clustered late in a much longer document
    (the last section always runs to the final page by construction, so
    a late first heading is what actually starves the coverage fraction)
    -- not a plausible whole-document outline.
    """
    candidates = [
        (15, "Chapter 1: Foundations", _HEAD, True),
        _body_line(15),
        (16, "Chapter 2: Structures", _HEAD, True),
        _body_line(16),
        (17, "Chapter 3: Applications", _HEAD, True),
        _body_line(17),
    ]
    assert sections_from_headings(candidates, total_pages=20) == []


def test_sections_from_headings_denylist_drops_detected_toc_heading():
    """The denylisted "Table of Contents" line is dropped as a candidate
    outright -- unlike the oversized-title case above, it never becomes a
    section title even via the no-drop guard's fallback, since no OTHER
    heading candidate survives on that page; the guard falls back to
    "Introduction" instead of silently dropping the page.
    """
    candidates = [
        (0, "Table of Contents", _HEAD, True),
        _body_line(0),
        (1, "Chapter 1: Foundations", _HEAD, True),
        _body_line(1),
        (2, "Chapter 2: Structures", _HEAD, True),
        _body_line(2),
        (3, "Chapter 3: Applications", _HEAD, True),
        _body_line(3),
    ]
    sections = sections_from_headings(candidates, total_pages=4)
    assert [s.title for s in sections] == [
        "Introduction",
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]
    assert (sections[0].page_start, sections[0].page_end) == (0, 0)


# --- Round 2 tuning: scaled cap, union split, no-drop guard (real-book fix) -


def test_max_heading_sections_uses_base_cap_for_short_documents():
    from app.pipeline.outline_detect import _max_heading_sections

    assert _max_heading_sections(total_pages=50) == 80  # 50 // 2 = 25, below the base cap
    assert _max_heading_sections(total_pages=160) == 80  # 160 // 2 = 80, exactly the base cap


def test_max_heading_sections_scales_up_for_long_documents():
    from app.pipeline.outline_detect import _max_heading_sections

    assert _max_heading_sections(total_pages=489) == 244  # the real-world regression case
    assert _max_heading_sections(total_pages=200) == 100  # 200 // 2 = 100


def test_max_heading_sections_never_exceeds_the_hard_cap():
    from app.pipeline.outline_detect import _max_heading_sections

    assert _max_heading_sections(total_pages=10_000) == 300  # 10000 // 2 = 5000, clamped to 300


def test_sections_from_headings_scaled_cap_admits_a_populous_real_tier():
    """A tier of 100 headings would fail the OLD fixed 80-section cap
    outright; a 250-page document's scaled cap (max(80, min(300, 125))) =
    125 admits it.
    """
    candidates = []
    for i in range(100):
        page = i * 2
        candidates.append((page, f"{i + 1}.0 Lesson Heading", _HEAD, True))
        candidates.append(_body_line(page))
    sections = sections_from_headings(candidates, total_pages=250)
    assert len(sections) == 100


def test_sections_from_headings_prefers_tier_with_most_sections_over_largest_size():
    """Regression: a sparse tier of larger-font one-off lines must not beat
    a smaller-font tier with far more headings just because it's larger --
    this was the real-world bug (a 489-page textbook's 177 real lesson
    headings at one size lost to 5 unrelated "N.N Practice" sheet headers
    at a larger size, because the larger tier trivially "qualified" via
    coverage -- the last section always runs to the document's final page
    by construction, regardless of how sparse the tier truly is).
    """
    dense_smaller = [(p, f"Chapter {i + 1}", _HEAD, True) for i, p in enumerate((0, 3, 6, 9, 12, 15))]
    sparse_larger = [(p, f"Sparse Marker {i + 1}", _HEAD * 1.3, True) for i, p in enumerate((1, 7, 13))]
    body_filler = [_body_line(p) for p in range(20)]  # so body size resolves to _BODY, not _HEAD
    sections = sections_from_headings(dense_smaller + sparse_larger + body_filler, total_pages=20)
    assert [s.title for s in sections] == [
        "Chapter 1",
        "Sparse Marker 1",
        "Chapter 2",
        "Chapter 3",
        "Sparse Marker 2",
        "Chapter 4",
        "Chapter 5",
        "Sparse Marker 3",
        "Chapter 6",
    ]


def test_sections_from_headings_union_split_includes_larger_tier_too_sparse_to_win_alone():
    """The winning tier's boundaries are the UNION of its own candidates
    and every candidate from a strictly larger tier -- even one that, on
    its own, has too few candidates to ever win the standalone check.
    """
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        (1, "Chapter 2: Structures", _HEAD, True),
        _body_line(1),
        (2, "Chapter 3: Applications", _HEAD, True),
        _body_line(2),
        (3, "Chapter 4: Practice", _HEAD, True),
        _body_line(3),
        (9, "A Sparse Larger Heading", _HEAD * 1.3, True),  # tier of 1 -- fails the count check alone
    ]
    sections = sections_from_headings(candidates, total_pages=10)
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
        "Chapter 4: Practice",
        "A Sparse Larger Heading",
    ]


def test_sections_from_headings_union_split_ignores_smaller_tier():
    """Symmetric check: a tier SMALLER than the winner is never unioned in
    -- only strictly larger tiers are.
    """
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        (1, "Chapter 2: Structures", _HEAD, True),
        _body_line(1),
        (2, "Chapter 3: Applications", _HEAD, True),
        _body_line(2),
        (5, "A Smaller Sub-Heading", _HEAD * 0.85, True),  # smaller than _HEAD -- never unioned in
    ]
    sections = sections_from_headings(candidates, total_pages=6)
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]


def test_sections_from_headings_respects_skip_before_page():
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),  # before the skip -- ignored
        _body_line(0),
        (1, "Chapter 2: Structures", _HEAD, True),
        _body_line(1),
        (2, "Chapter 3: Applications", _HEAD, True),
        _body_line(2),
        (3, "Chapter 4: Practice", _HEAD, True),
        _body_line(3),
    ]
    sections = sections_from_headings(candidates, total_pages=4, skip_before_page=1)
    assert [s.title for s in sections] == [
        "Chapter 2: Structures",
        "Chapter 3: Applications",
        "Chapter 4: Practice",
    ]


def test_detect_sections_prefers_bookmarks_over_heading_tier():
    toc = [(1, "A", 0), (1, "B", 3), (1, "C", 6)]
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        (3, "Chapter 2: Structures", _HEAD, True),
        _body_line(3),
        (6, "Chapter 3: Applications", _HEAD, True),
        _body_line(6),
    ]
    sections = detect_sections(toc, total_pages=9, pages_per_window=12, heading_candidates=candidates)
    assert [s.title for s in sections] == ["A", "B", "C"]  # bookmark titles, not heading titles


def test_detect_sections_uses_heading_tier_when_bookmarks_unusable():
    candidates = [
        (0, "Chapter 1: Foundations", _HEAD, True),
        _body_line(0),
        (2, "Chapter 2: Structures", _HEAD, True),
        _body_line(2),
        (4, "Chapter 3: Applications", _HEAD, True),
        _body_line(4),
    ]
    sections = detect_sections([], total_pages=6, pages_per_window=12, heading_candidates=candidates)
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]


def test_detect_sections_falls_back_to_windows_when_heading_tier_also_fails():
    candidates = [(0, "Chapter 1: Foundations", _HEAD, True), _body_line(0)]  # only 1 -- fails the count check
    sections = detect_sections([], total_pages=13, pages_per_window=12, heading_candidates=candidates)
    assert sections[0].title == "Pages 1–12"


# --- Real-fixture pins: tier order is unaffected by adding the heading tier -

def test_detect_sections_with_bookmarks_pdf_still_prefers_bookmarks_over_headings():
    sections = _detect_sections_for_fixture("with_bookmarks.pdf")
    assert [s.title for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]


def test_detect_sections_no_bookmarks_pdf_still_falls_back_to_windows():
    """Real-data pin: no_bookmarks.pdf's uniform-size body text produces
    zero heading candidates, so it must still take the page-window
    fallback exactly as it did before the heading-detection tier existed.
    """
    sections = _detect_sections_for_fixture("no_bookmarks.pdf")
    assert len(sections) == 1
    assert sections[0].title == "Pages 1–10"
