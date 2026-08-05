from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from app.db.identity import content_hash_for, normalize_text
from app.pipeline.import_adapters import NormalizedSection, NormalizedSourceDocument
from app.pipeline.source_locators import HeadingLocator

HTML_FORMAT_NAME = "html"
HTML_MEDIA_TYPE = "text/html"
HTML_EXTRACTOR_VERSION = "html-stdlib-v1"

_BLOCK_TAGS = {"address", "article", "aside", "blockquote", "div", "footer", "header", "li", "main", "p", "section"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_CONTENT_TAGS = {"script", "style", "iframe", "object", "embed", "svg", "math"}
_SAFE_LINK_SCHEMES = {"", "http", "https", "mailto"}
_MARKDOWN_TEXT_ESCAPE_RE = re.compile(r"([\\`*_{}\[\]()<>])")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def looks_like_html_text(text: str) -> bool:
    sample = text[:4096].lower()
    return any(marker in sample for marker in ("<html", "<!doctype html", "<body", "<h1", "<p", "<div"))


def _safe_href(href: str) -> str | None:
    href = _CONTROL_CHARS_RE.sub("", href.strip())
    if any(char in href for char in "[]()<>"):
        return None
    parsed = urlparse(href)
    if parsed.scheme.lower() in _SAFE_LINK_SCHEMES:
        return quote(href, safe="/:#?&=@%+~,.;-")
    return None


def _escape_markdown_text(text: str) -> str:
    return _MARKDOWN_TEXT_ESCAPE_RE.sub(r"\\\1", text)


class _MarkdownHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading_level: int | None = None
        self.link_href_stack: list[str | None] = []
        self.skip_depth = 0
        self.pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.skip_depth:
            if tag in _SKIP_CONTENT_TAGS:
                self.skip_depth += 1
            return
        if tag in _SKIP_CONTENT_TAGS:
            self.skip_depth = 1
            return
        if tag in _HEADING_TAGS:
            self._paragraph_break()
            self.heading_level = int(tag[1])
            self.parts.append("#" * self.heading_level + " ")
            return
        if tag in _BLOCK_TAGS:
            self._paragraph_break()
            return
        if tag == "br":
            self.parts.append("\n")
            return
        if tag == "pre":
            self._paragraph_break()
            self.pre_depth += 1
            self.parts.append("```\n")
            return
        if tag == "a":
            href = dict(attrs).get("href")
            self.link_href_stack.append(_safe_href(href) if href else None)
            if self.link_href_stack[-1]:
                self.parts.append("[")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_depth:
            if tag in _SKIP_CONTENT_TAGS:
                self.skip_depth -= 1
            return
        if tag in _HEADING_TAGS:
            self.heading_level = None
            self._paragraph_break()
            return
        if tag in _BLOCK_TAGS:
            self._paragraph_break()
            return
        if tag == "pre" and self.pre_depth:
            self.pre_depth -= 1
            self.parts.append("\n```")
            self._paragraph_break()
            return
        if tag == "a" and self.link_href_stack:
            href = self.link_href_stack.pop()
            if href:
                while self.parts and self.parts[-1] == " ":
                    self.parts.pop()
                self.parts.append(f"]({href})")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.pre_depth:
            self.parts.append(data)
        else:
            collapsed = " ".join(data.split())
            if not collapsed:
                return
            if self.parts and not self.parts[-1].endswith((" ", "\n", "[")):
                self.parts.append(" ")
            self.parts.append(_escape_markdown_text(collapsed))
            if not collapsed.endswith((".", ",", ";", ":", "!", "?")):
                self.parts.append(" ")

    def _paragraph_break(self) -> None:
        while self.parts and self.parts[-1] == " ":
            self.parts.pop()
        if self.parts and not "".join(self.parts[-2:]).endswith("\n\n"):
            self.parts.append("\n\n")

    def markdown(self) -> str:
        text = "".join(self.parts).replace("\n \n", "\n\n")
        text = re.sub(r"\s+([.,;:!?])", r"\1", text)
        return normalize_text(text)


def html_to_markdown(text: str) -> str:
    parser = _MarkdownHTMLParser()
    parser.feed(text)
    parser.close()
    return parser.markdown()


def _sections_from_markdown(markdown: str, *, asset_id: str | None) -> list[NormalizedSection]:
    sections: list[NormalizedSection] = []
    current_title = "HTML Document"
    current_lines: list[str] = []

    def _flush() -> None:
        if not current_lines:
            return
        body_md = normalize_text("\n".join(current_lines))
        if not body_md:
            return
        sections.append(
            NormalizedSection(
                stable_section_id=None,
                title=current_title,
                body_md=body_md,
                content_hash=content_hash_for(body_md),
                source_locator=HeadingLocator(asset_id=asset_id, heading_path=[current_title]),
                chapter_label=None,
                asset_id=asset_id,
                source_format=HTML_FORMAT_NAME,
                pages=[(0, body_md)],
            )
        )

    for line in markdown.splitlines():
        if line.startswith("#"):
            _flush()
            current_lines = [line]
            current_title = line.lstrip("#").strip() or "HTML Document"
        else:
            current_lines.append(line)
    _flush()
    return sections


def extract_html_document(path: Path, *, asset_id: str | None) -> NormalizedSourceDocument:
    text = path.read_text(encoding="utf-8")
    markdown = html_to_markdown(text)
    return NormalizedSourceDocument(
        metadata={"page_count": 1, "total_chars": len(markdown)},
        sections=_sections_from_markdown(markdown, asset_id=asset_id),
        warnings=[],
        failures=[],
        extractor_name="html-stdlib",
        extractor_version=HTML_EXTRACTOR_VERSION,
        source_format=HTML_FORMAT_NAME,
    )


class HtmlDocumentAdapter:
    format_name = HTML_FORMAT_NAME
    format_version = "1"
    media_type = HTML_MEDIA_TYPE

    def sniff(self, asset: Any) -> bool:
        try:
            return looks_like_html_text(Path(asset.stored_path).read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            return False

    def extract(self, asset: Any) -> NormalizedSourceDocument:
        return extract_html_document(Path(asset.stored_path), asset_id=asset.id)
