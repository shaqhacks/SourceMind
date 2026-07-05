"""Content-addressed identity helpers for sections and cards.

Both ids are derived, not random, so re-ingesting identical source text (or
re-running deterministic parsing) reproduces the same id instead of minting a
new row every time. `occurrence` disambiguates sections whose normalized
text is byte-identical within the same course (e.g. a repeated "Exercises"
heading) so they don't collide onto the same id.
"""

from __future__ import annotations

import hashlib
import unicodedata

_ID_LENGTH = 24


def normalize_text(text: str) -> str:
    """Normalize markdown body text before hashing/comparison.

    Strips trailing whitespace per line, collapses runs of blank lines to a
    single blank line, and applies Unicode NFC normalization — so
    whitespace-only edits never change the derived id.
    """
    normalized = unicodedata.normalize("NFC", text)
    lines = [line.rstrip() for line in normalized.splitlines()]

    collapsed: list[str] = []
    blank_run = False
    for line in lines:
        if line == "":
            if blank_run:
                continue
            blank_run = True
        else:
            blank_run = False
        collapsed.append(line)

    return "\n".join(collapsed).strip("\n")


def content_hash_for(normalized_text: str) -> str:
    """Pure sha256 of normalized body text — no course/occurrence mixed in."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def section_id_for(course_id: str, normalized_text: str, occurrence: int) -> str:
    digest = hashlib.sha256(
        f"{course_id}\n{occurrence}\n{normalized_text}".encode("utf-8")
    ).hexdigest()
    return digest[:_ID_LENGTH]


def card_id_for(section_id: str, front: str, back: str) -> str:
    digest = hashlib.sha256(f"{section_id}\n{front}\n{back}".encode("utf-8")).hexdigest()
    return digest[:_ID_LENGTH]
