"""Deterministic outline boundary detection: bookmark-first with a
page-window fallback. No LLM calls, ever (ingest prime directive).
"""

from __future__ import annotations

from dataclasses import dataclass

_MIN_TOC_SECTIONS = 3
_MIN_USABLE_SECTIONS = 2


@dataclass
class SectionBounds:
    title: str
    page_start: int  # 0-based, inclusive
    page_end: int  # 0-based, inclusive


def sections_from_toc(
    toc_entries: list[tuple[int, str, int]], total_pages: int
) -> list[SectionBounds]:
    """Bookmark-first: level-1 entries are the section boundaries, unless
    level-1 has fewer than _MIN_TOC_SECTIONS entries, in which case level-2
    is used instead (a deliberately simple two-level rule — no fancy
    level-picking heuristic). Returns [] if there are no usable bookmarks at
    all, so callers fall back to sections_from_page_windows.
    """
    entries = [(lvl, title.strip(), pg) for (lvl, title, pg) in toc_entries if title and title.strip()]
    if not entries:
        return []

    level1 = sorted((e for e in entries if e[0] == 1), key=lambda e: e[2])
    level2 = sorted((e for e in entries if e[0] == 2), key=lambda e: e[2])

    if len(level1) >= _MIN_TOC_SECTIONS:
        chosen = level1
    elif level2:
        chosen = level2
    else:
        chosen = level1

    if not chosen:
        return []

    last_page = max(total_pages - 1, 0)
    sections: list[SectionBounds] = []
    for i, (_lvl, title, page) in enumerate(chosen):
        start = max(0, min(page, last_page))
        if i + 1 < len(chosen):
            end = max(start, min(chosen[i + 1][2] - 1, last_page))
        else:
            end = last_page
        sections.append(SectionBounds(title=title, page_start=start, page_end=end))
    return sections


def sections_from_page_windows(total_pages: int, pages_per_window: int) -> list[SectionBounds]:
    """No-bookmark fallback: fixed page-range windows with 1-based-readable
    placeholder titles.
    """
    if total_pages <= 0:
        return []
    pages_per_window = max(1, pages_per_window)

    sections: list[SectionBounds] = []
    start = 0
    while start < total_pages:
        end = min(start + pages_per_window - 1, total_pages - 1)
        sections.append(
            SectionBounds(title=f"Pages {start + 1}–{end + 1}", page_start=start, page_end=end)
        )
        start = end + 1
    return sections


def detect_sections(
    toc_entries: list[tuple[int, str, int]], total_pages: int, pages_per_window: int
) -> list[SectionBounds]:
    """Bookmark-first with a page-window fallback when bookmarks yield fewer
    than _MIN_USABLE_SECTIONS sections.
    """
    toc_sections = sections_from_toc(toc_entries, total_pages)
    if len(toc_sections) >= _MIN_USABLE_SECTIONS:
        return toc_sections
    return sections_from_page_windows(total_pages, pages_per_window)
