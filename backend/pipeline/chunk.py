"""Page-level text chunking with a sliding window and configurable overlap.

Pure Python — no I/O, no network calls, fully unit-testable.
Duck-types on page objects that expose ``.page_number`` (int) and ``.text`` (str).
"""
from __future__ import annotations


def chunk_pages(
    pages,
    target_words: int = 350,
    overlap_words: int = 60,
) -> list[tuple[str, str]]:
    """Chunk a sequence of pages into overlapping text windows.

    Args:
        pages: iterable of objects with .page_number (int) and .text (str).
        target_words: number of words per chunk window.
        overlap_words: words shared between consecutive windows.

    Returns:
        list of ``(source_ref, content)`` tuples where ``source_ref`` is
        ``"p.N"`` for single-page chunks and ``"pp.A-B"`` for multi-page ones.
        Returns ``[]`` when all pages are empty/whitespace.
    """
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
