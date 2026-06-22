"""URL source parser: turn already-fetched HTML into readable text.

Fetching the URL (and the SSRF guard around it) is a separate concern handled at
the network boundary (T9); this parser only normalizes content that has already
been retrieved, so it is fully testable offline.
"""

from __future__ import annotations

import html as html_module
import re

from SourceMind.backend.services.ingest.base import clean_text, reject_if_unusable
from SourceMind.backend.services.ingest.security import sanitize_source

_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_BLOCK_BOUNDARY = re.compile(r"</(p|div|section|article|h[1-6]|li|br)\s*>", re.IGNORECASE)


class UrlParser:
    source_type = "url"

    def normalize(self, payload: str) -> str:
        content = payload or ""
        content = _SCRIPT_OR_STYLE.sub(" ", content)
        # Preserve block structure as line breaks before stripping tags.
        content = _BLOCK_BOUNDARY.sub("\n", content)
        content = _TAG.sub(" ", content)
        content = html_module.unescape(content)
        # Third-party HTML may carry prompt-injection aimed at the downstream LLM.
        content, _injection = sanitize_source(content)
        return reject_if_unusable(clean_text(content), source_type=self.source_type)
