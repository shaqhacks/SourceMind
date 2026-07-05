"""Page-level text chunking with a sliding window and configurable overlap.

Pure Python — no network calls, fully unit-testable. Duck-types on page
objects that expose ``.page_number`` (int) and ``.text`` (str), and on section
descriptors (dict or attribute-style) that expose ``section_id``,
``page_start``, and ``page_end``.
"""
from __future__ import annotations

from SourceMind.backend import config


def _get(obj, key: str):
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def _chunk_page_window(pages, target_words: int, overlap_words: int) -> list[tuple[str, str]]:
    """Sliding-window chunker over *pages* only (no section prefix on source_ref)."""
    step = max(1, target_words - overlap_words)

    # Flatten non-empty pages into (word, page_number) pairs.
    word_pairs: list[tuple[str, int]] = []
    for page in pages:
        if not page.text or not page.text.strip():
            continue
        for word in page.text.split():
            word_pairs.append((word, page.page_number))

    if not word_pairs:
        return []

    total = len(word_pairs)
    chunks: list[tuple[str, str]] = []
    start = 0
    while start < total:
        end = min(start + target_words, total)
        window = word_pairs[start:end]
        content = " ".join(w for w, _ in window)
        pages_in_window = sorted(set(pn for _, pn in window))
        if len(pages_in_window) == 1:
            source_ref = f"p.{pages_in_window[0]}"
        else:
            source_ref = f"pp.{pages_in_window[0]}-{pages_in_window[-1]}"
        chunks.append((source_ref, content))
        start += step

    return chunks


def chunk_pages(
    pages,
    target_words: int | None = None,
    overlap_words: int | None = None,
    sections: list | None = None,
) -> list[tuple[str, str]]:
    """Chunk a sequence of pages into overlapping text windows.

    When *sections* is given (section descriptors exposing ``section_id``,
    ``page_start``, ``page_end`` — dict or attribute-style), chunking runs
    independently within each section's page range so a single chunk never
    straddles two chapters, and each ``source_ref`` is prefixed with its
    section_id (``"{section_id}:p.N"`` / ``"{section_id}:pp.A-B"``) so
    citations can reference the section a chunk belongs to. Any pages not
    covered by a section (gaps between/outside section ranges, or when
    *sections* is empty/None) fall back to whole-document windowing with the
    original ref format (``"p.N"`` / ``"pp.A-B"``).

    Args:
        pages: iterable of objects with .page_number (int) and .text (str).
        target_words: words per chunk window. Defaults to
            config.chunk_target_words() (env SOURCEMIND_CHUNK_TARGET_WORDS).
        overlap_words: words shared between consecutive windows. Defaults to
            config.chunk_overlap_words() (env SOURCEMIND_CHUNK_OVERLAP_WORDS).
        sections: optional list of section descriptors for section-aware chunking.

    Returns:
        list of ``(source_ref, content)`` tuples. Returns ``[]`` when all
        pages are empty/whitespace.
    """
    if target_words is None:
        target_words = config.chunk_target_words()
    if overlap_words is None:
        overlap_words = config.chunk_overlap_words()

    if not sections:
        return _chunk_page_window(pages, target_words, overlap_words)

    pages_list = list(pages)
    chunks: list[tuple[str, str]] = []
    covered_page_numbers: set[int] = set()

    for section in sorted(sections, key=lambda s: _get(s, "page_start")):
        sid = _get(section, "section_id")
        p_start = _get(section, "page_start")
        p_end = _get(section, "page_end")
        section_pages = [p for p in pages_list if p_start <= p.page_number <= p_end]
        if not section_pages:
            continue
        covered_page_numbers.update(p.page_number for p in section_pages)
        for source_ref, content in _chunk_page_window(section_pages, target_words, overlap_words):
            chunks.append((f"{sid}:{source_ref}", content))

    # Pages outside every section's range (front matter, gaps, appendices, ...)
    # still get chunked — via the original whole-document ref format — so no
    # content is silently dropped.
    leftover_pages = [p for p in pages_list if p.page_number not in covered_page_numbers]
    if leftover_pages:
        chunks.extend(_chunk_page_window(leftover_pages, target_words, overlap_words))

    return chunks
