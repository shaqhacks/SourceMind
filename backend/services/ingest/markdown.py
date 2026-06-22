"""Markdown (.md) source parser: strip frontmatter and inline syntax to text."""

from __future__ import annotations

import re

try:
    import frontmatter
except ImportError:  # pragma: no cover - dependency declared in dev/build deps
    frontmatter = None

from SourceMind.backend.services.ingest.base import clean_text, reject_if_unusable

_FENCE = re.compile(r"^```.*?$", re.MULTILINE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_LIST_MARKER = re.compile(r"^\s*([-*+]|\d+\.)\s+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)")
_FRONTMATTER_FENCE = re.compile(r"^---\s*$", re.MULTILINE)


class MarkdownParser:
    source_type = "markdown"

    def normalize(self, payload: str) -> str:
        body = payload or ""
        if frontmatter is not None:
            try:
                body = frontmatter.loads(body).content
            except Exception:
                body = _FRONTMATTER_FENCE.sub("", body)
        else:  # pragma: no cover - frontmatter is available in test/build envs
            body = _FRONTMATTER_FENCE.sub("", body)

        body = _IMAGE.sub(r"\1", body)
        body = _LINK.sub(r"\1", body)
        body = _FENCE.sub("", body)
        body = _HEADING.sub("", body)
        body = _BLOCKQUOTE.sub("", body)
        body = _LIST_MARKER.sub("", body)
        body = _EMPHASIS.sub("", body)
        return reject_if_unusable(clean_text(body), source_type=self.source_type)
