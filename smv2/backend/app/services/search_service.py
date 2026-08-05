from __future__ import annotations

import base64
import html
import json
import re
from typing import Any

from app.db.engine import get_session
from app.schemas import SearchResultOut, SearchResultsOut, SourceLocatorOut
from app.services import search_index

_VALID_DOCUMENT_TYPES = {"section", "lesson", "note", "highlight"}
_MAX_LIMIT = 50
_TOKEN_RE = re.compile(r"\S+")
_DOC_TYPE_ORDER = {"section": 0, "lesson": 1, "note": 2, "highlight": 3}


def _normalize_query(query: str) -> str:
    return " ".join(_TOKEN_RE.findall(query.strip().casefold()))


def _encode_cursor(sort_key: tuple[Any, ...]) -> str:
    payload = json.dumps(sort_key, separators=(",", ":"), ensure_ascii=True)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None) -> tuple[Any, ...] | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        decoded = json.loads(raw)
        if not isinstance(decoded, list):
            return None
        return tuple(decoded)
    except Exception:
        return None


def _token_count(text: str, tokens: list[str]) -> int:
    haystack = text.casefold()
    return sum(haystack.count(token) for token in tokens)


def _score(row: dict[str, Any], tokens: list[str], fts_keys: set[str]) -> float:
    title = str(row["title"] or "")
    body = str(row["body"] or "")
    score = 0.0
    if row["doc_key"] in fts_keys:
        score += 10.0
    for token in tokens:
        title_folded = title.casefold()
        if title_folded == token:
            score += 100.0
        elif token in title_folded:
            score += 50.0
    score += _token_count(title, tokens) * 5.0
    score += _token_count(body, tokens)
    return score


def _matches(row: dict[str, Any], tokens: list[str], fts_keys: set[str]) -> bool:
    if row["doc_key"] in fts_keys:
        return True
    haystack = f"{row['title']}\n{row['body']}".casefold()
    return all(token in haystack for token in tokens)


def _sort_key(row: dict[str, Any], score: float) -> tuple[Any, ...]:
    return (
        -score,
        _DOC_TYPE_ORDER.get(str(row["doc_type"]), 99),
        str(row["doc_key"]),
        int(row["order_index"] or 0),
    )


def _excerpt(body: str, query: str, width: int = 220) -> str:
    folded = body.casefold()
    first_token = query.split()[0] if query.split() else ""
    index = folded.find(first_token) if first_token else -1
    if index < 0:
        index = 0
    start = max(0, index - width // 3)
    end = min(len(body), start + width)
    snippet = body[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(body):
        snippet = snippet + "..."
    return html.escape(snippet, quote=False)


def _to_result(row: dict[str, Any], score: float, sort_key: tuple[Any, ...], query: str) -> SearchResultOut:
    locator = SourceLocatorOut(
        page=row.get("source_page"),
        heading=row.get("source_heading"),
        chapter=row.get("source_chapter"),
        slide=row.get("source_slide"),
    )
    return SearchResultOut(
        doc_type=row["doc_type"],
        course_id=row["course_id"],
        section_id=row.get("section_id"),
        asset_id=row.get("asset_id"),
        title=row["title"],
        excerpt_md=_excerpt(str(row["body"] or ""), query),
        source_locator=locator,
        score=score,
        cursor_token=_encode_cursor(sort_key),
    )


def search_course(
    course_id: str,
    query: str,
    *,
    document_types: list[str] | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> SearchResultsOut:
    normalized = _normalize_query(query)
    if not normalized:
        raise ValueError("query must not be empty")
    requested_types = list(dict.fromkeys(document_types or []))
    invalid_types = sorted(set(requested_types) - _VALID_DOCUMENT_TYPES)
    if invalid_types:
        raise ValueError(f"unsupported document_type: {', '.join(invalid_types)}")
    limit = max(1, min(limit, _MAX_LIMIT))

    session = get_session()
    try:
        backend = search_index.ensure_search_backend(session)
        fts_keys = (
            search_index.matching_fts_doc_keys(session, course_id, normalized)
            if backend == "fts5"
            else set()
        )
        tokens = normalized.split()
        candidates = []
        for row in search_index.document_rows(
            session,
            course_id,
            requested_types or None,
            tokens=tokens,
            fts_doc_keys=fts_keys,
        ):
            if not _matches(row, tokens, fts_keys):
                continue
            score = _score(row, tokens, fts_keys)
            if score <= 0:
                continue
            candidates.append((row, score, _sort_key(row, score)))

        candidates.sort(key=lambda item: item[2])
        decoded_cursor = _decode_cursor(cursor)
        if decoded_cursor is not None:
            candidates = [item for item in candidates if item[2] > decoded_cursor]
        page = candidates[:limit]
        next_cursor = _encode_cursor(page[-1][2]) if len(candidates) > limit and page else None
        return SearchResultsOut(
            items=[_to_result(row, score, sort_key, normalized) for row, score, sort_key in page],
            next_cursor=next_cursor,
            backend=backend,
            sanitized_excerpts=True,
        )
    finally:
        session.close()


def rebuild_course_index(course_id: str | None = None) -> int:
    session = get_session()
    try:
        count = search_index.rebuild_course_documents(session, course_id)
        session.commit()
        return count
    finally:
        session.close()
