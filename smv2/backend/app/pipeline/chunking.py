"""Deterministic text chunking — no LLM calls.

Splits a section's per-page markdown into ~target_chars chunks, breaking
only at paragraph boundaries so a chunk never cuts a sentence in half. Each
chunk is attributed to the page its first paragraph came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TARGET_CHUNK_CHARS = 1400
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


@dataclass
class TextChunk:
    text: str
    page: int


def chunk_pages(
    pages: list[tuple[int, str]], target_chars: int = _TARGET_CHUNK_CHARS
) -> list[TextChunk]:
    """pages is a list of (page_number, markdown_text), 0-based, in order.

    A single paragraph longer than target_chars becomes its own oversized
    chunk rather than being split mid-paragraph — an acceptable, rare edge
    case given the "never split a paragraph" rule.
    """
    chunks: list[TextChunk] = []
    buffer_parts: list[str] = []
    buffer_len = 0
    buffer_page: int | None = None

    def flush() -> None:
        nonlocal buffer_parts, buffer_len, buffer_page
        if buffer_parts and buffer_page is not None:
            text = "\n\n".join(buffer_parts).strip()
            if text:
                chunks.append(TextChunk(text=text, page=buffer_page))
        buffer_parts = []
        buffer_len = 0
        buffer_page = None

    for page_number, page_text in pages:
        paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(page_text or "") if p.strip()]
        for para in paragraphs:
            if buffer_len + len(para) > target_chars and buffer_parts:
                flush()
            if buffer_page is None:
                buffer_page = page_number
            buffer_parts.append(para)
            buffer_len += len(para) + 2  # account for the joining "\n\n"

    flush()
    return chunks
