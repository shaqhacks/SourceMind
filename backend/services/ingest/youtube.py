"""YouTube transcript parser.

Accepts an already-fetched transcript as a list of segment dicts
(``{"text": ...}``), a list of strings, or a single string. Fetching the
transcript over the network is handled at the boundary (T9); this parser only
joins and normalizes it.
"""

from __future__ import annotations

from typing import Any

from SourceMind.backend.services.ingest.base import clean_text, reject_if_unusable
from SourceMind.backend.services.ingest.security import sanitize_source


class YouTubeParser:
    source_type = "youtube"

    def normalize(self, payload: Any) -> str:
        if isinstance(payload, str):
            text = payload
        elif isinstance(payload, list):
            parts: list[str] = []
            for segment in payload:
                if isinstance(segment, dict):
                    parts.append(str(segment.get("text", "")))
                else:
                    parts.append(str(segment))
            text = " ".join(parts)
        else:
            text = str(payload or "")
        # Auto-generated transcripts can be poisoned with injected instructions.
        text, _injection = sanitize_source(text)
        return reject_if_unusable(clean_text(text), source_type=self.source_type)
