from __future__ import annotations

from app.pipeline.outline_detect import (
    detect_sections,
    sections_from_page_windows,
    sections_from_toc,
)


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
