"""Pasted plain-text source parser."""

from __future__ import annotations

from SourceMind.backend.services.ingest.base import clean_text, reject_if_unusable


class TextParser:
    source_type = "text"

    def normalize(self, payload: str) -> str:
        return reject_if_unusable(clean_text(payload or ""), source_type=self.source_type)
