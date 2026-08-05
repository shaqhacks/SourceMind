from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.db.models import Highlight, Note, Section

SearchBackend = Literal["fts5", "like"]

_CREATE_DOCUMENTS_SQL = """
CREATE TABLE IF NOT EXISTS search_documents (
    doc_key TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,
    course_id TEXT NOT NULL,
    section_id TEXT,
    asset_id TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    source_page INTEGER,
    source_heading TEXT,
    source_chapter TEXT,
    source_slide TEXT
)
"""


def _connection(session_or_connection: Session | Connection) -> Connection:
    if isinstance(session_or_connection, Connection):
        return session_or_connection
    return session_or_connection.connection()


def fts5_available(session: Session | Connection) -> bool:
    connection = _connection(session)
    try:
        connection.exec_driver_sql("CREATE VIRTUAL TABLE temp.__smv2_fts5_probe USING fts5(body)")
        connection.exec_driver_sql("DROP TABLE temp.__smv2_fts5_probe")
        return True
    except Exception:
        try:
            connection.exec_driver_sql("DROP TABLE IF EXISTS temp.__smv2_fts5_probe")
        except Exception:
            pass
        return False


def ensure_core_table(session: Session) -> None:
    session.execute(text(_CREATE_DOCUMENTS_SQL))
    session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_search_documents_course ON search_documents(course_id)")
    )
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_search_documents_type_course "
            "ON search_documents(course_id, doc_type)"
        )
    )


def ensure_search_backend(session: Session) -> SearchBackend:
    ensure_core_table(session)
    if not fts5_available(session):
        _drop_fts(session)
        return "like"
    _ensure_fts(session)
    return "fts5"


def _ensure_fts(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts
            USING fts5(doc_key UNINDEXED, title, body)
            """
        )
    )


def _drop_fts(session: Session) -> None:
    session.execute(text("DROP TABLE IF EXISTS search_documents_fts"))


def _has_fts(session: Session) -> bool:
    row = session.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'search_documents_fts'"
        )
    ).first()
    return row is not None


def _doc_key(doc_type: str, source_id: str) -> str:
    return f"{doc_type}:{source_id}"


def _source_page(section: Section) -> int | None:
    return section.page_start + 1 if section.page_start is not None else None


def _upsert_document(
    session: Session,
    *,
    doc_key: str,
    doc_type: str,
    course_id: str,
    section_id: str | None,
    asset_id: str | None,
    title: str,
    body: str | None,
    order_index: int,
    source_page: int | None,
    source_heading: str | None,
    source_chapter: str | None,
    source_slide: str | None = None,
) -> None:
    ensure_search_backend(session)
    body_text = body or ""
    if not body_text.strip():
        _delete_document(session, doc_key)
        return
    session.execute(
        text(
            """
            INSERT INTO search_documents (
                doc_key, doc_type, course_id, section_id, asset_id, title, body,
                order_index, source_page, source_heading, source_chapter, source_slide
            )
            VALUES (
                :doc_key, :doc_type, :course_id, :section_id, :asset_id, :title, :body,
                :order_index, :source_page, :source_heading, :source_chapter, :source_slide
            )
            ON CONFLICT(doc_key) DO UPDATE SET
                doc_type = excluded.doc_type,
                course_id = excluded.course_id,
                section_id = excluded.section_id,
                asset_id = excluded.asset_id,
                title = excluded.title,
                body = excluded.body,
                order_index = excluded.order_index,
                source_page = excluded.source_page,
                source_heading = excluded.source_heading,
                source_chapter = excluded.source_chapter,
                source_slide = excluded.source_slide
            """
        ),
        {
            "doc_key": doc_key,
            "doc_type": doc_type,
            "course_id": course_id,
            "section_id": section_id,
            "asset_id": asset_id,
            "title": title,
            "body": body_text,
            "order_index": order_index,
            "source_page": source_page,
            "source_heading": source_heading,
            "source_chapter": source_chapter,
            "source_slide": source_slide,
        },
    )
    if _has_fts(session):
        session.execute(text("DELETE FROM search_documents_fts WHERE doc_key = :doc_key"), {"doc_key": doc_key})
        session.execute(
            text(
                "INSERT INTO search_documents_fts (doc_key, title, body) "
                "VALUES (:doc_key, :title, :body)"
            ),
            {"doc_key": doc_key, "title": title, "body": body_text},
        )


def _delete_document(session: Session, doc_key: str) -> None:
    ensure_core_table(session)
    session.execute(text("DELETE FROM search_documents WHERE doc_key = :doc_key"), {"doc_key": doc_key})
    if _has_fts(session):
        session.execute(text("DELETE FROM search_documents_fts WHERE doc_key = :doc_key"), {"doc_key": doc_key})


def upsert_section_document(session: Session, section: Section) -> None:
    _upsert_document(
        session,
        doc_key=_doc_key("section", section.id),
        doc_type="section",
        course_id=section.course_id,
        section_id=section.id,
        asset_id=section.asset_id,
        title=section.title,
        body=section.body_md,
        order_index=section.order_index,
        source_page=_source_page(section),
        source_heading=section.title,
        source_chapter=section.chapter_label,
    )


def upsert_lesson_document(session: Session, section: Section) -> None:
    _upsert_document(
        session,
        doc_key=_doc_key("lesson", section.id),
        doc_type="lesson",
        course_id=section.course_id,
        section_id=section.id,
        asset_id=section.asset_id,
        title=f"Lesson: {section.title}",
        body=section.lesson_md,
        order_index=section.order_index,
        source_page=_source_page(section),
        source_heading=section.title,
        source_chapter=section.chapter_label,
    )


def upsert_note_document(session: Session, note: Note) -> None:
    section = session.get(Section, note.section_id)
    _upsert_document(
        session,
        doc_key=_doc_key("note", note.id),
        doc_type="note",
        course_id=note.course_id,
        section_id=note.section_id,
        asset_id=note.id,
        title=f"Note: {section.title if section is not None else note.section_id}",
        body=note.note_md,
        order_index=section.order_index if section is not None else 0,
        source_page=note.page + 1,
        source_heading=section.title if section is not None else None,
        source_chapter=section.chapter_label if section is not None else None,
    )


def upsert_highlight_document(session: Session, highlight: Highlight) -> None:
    section = session.get(Section, highlight.section_id)
    body = "\n\n".join(part for part in (highlight.exact, highlight.note_md) if part)
    _upsert_document(
        session,
        doc_key=_doc_key("highlight", highlight.id),
        doc_type="highlight",
        course_id=highlight.course_id,
        section_id=highlight.section_id,
        asset_id=highlight.id,
        title=f"Highlight: {section.title if section is not None else highlight.section_id}",
        body=body,
        order_index=section.order_index if section is not None else 0,
        source_page=highlight.page + 1 if highlight.page is not None else None,
        source_heading=section.title if section is not None else None,
        source_chapter=section.chapter_label if section is not None else None,
    )


def delete_note_document(session: Session, note_id: str) -> None:
    _delete_document(session, _doc_key("note", note_id))


def delete_highlight_document(session: Session, highlight_id: str) -> None:
    _delete_document(session, _doc_key("highlight", highlight_id))


def delete_course_documents(session: Session, course_id: str) -> None:
    ensure_core_table(session)
    session.execute(text("DELETE FROM search_documents WHERE course_id = :course_id"), {"course_id": course_id})
    if _has_fts(session):
        session.execute(
            text(
                """
                DELETE FROM search_documents_fts
                WHERE doc_key NOT IN (SELECT doc_key FROM search_documents)
                """
            )
        )


def rebuild_course_documents(session: Session, course_id: str | None = None) -> int:
    ensure_search_backend(session)
    if course_id is None:
        session.execute(text("DELETE FROM search_documents"))
        if _has_fts(session):
            session.execute(text("DELETE FROM search_documents_fts"))
    else:
        delete_course_documents(session, course_id)

    section_query = session.query(Section)
    if course_id is not None:
        section_query = section_query.filter(Section.course_id == course_id)
    sections = section_query.order_by(Section.course_id, Section.order_index, Section.id).all()
    for section in sections:
        upsert_section_document(session, section)
        upsert_lesson_document(session, section)

    note_query = session.query(Note)
    if course_id is not None:
        note_query = note_query.filter(Note.course_id == course_id)
    for note in note_query.order_by(Note.course_id, Note.section_id, Note.id).all():
        upsert_note_document(session, note)

    highlight_query = session.query(Highlight)
    if course_id is not None:
        highlight_query = highlight_query.filter(Highlight.course_id == course_id)
    for highlight in highlight_query.order_by(Highlight.course_id, Highlight.section_id, Highlight.id).all():
        upsert_highlight_document(session, highlight)

    count_row = session.execute(
        text(
            "SELECT COUNT(*) FROM search_documents"
            + (" WHERE course_id = :course_id" if course_id is not None else "")
        ),
        {"course_id": course_id} if course_id is not None else {},
    ).first()
    return int(count_row[0] if count_row is not None else 0)


def matching_fts_doc_keys(session: Session, course_id: str, query: str) -> set[str]:
    if not _has_fts(session):
        return set()
    tokens = [token for token in query.split() if token]
    if not tokens:
        return set()
    fts_query = " ".join(f'"{token.replace("\"", "\"\"")}"' for token in tokens)
    rows = session.execute(
        text(
            """
            SELECT f.doc_key
            FROM search_documents_fts f
            JOIN search_documents d ON d.doc_key = f.doc_key
            WHERE d.course_id = :course_id
            AND search_documents_fts MATCH :query
            """
        ),
        {"course_id": course_id, "query": fts_query},
    ).mappings()
    return {str(row["doc_key"]) for row in rows}


def _escape_like_token(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def document_rows(
    session: Session,
    course_id: str,
    document_types: list[str] | None = None,
    *,
    tokens: list[str] | None = None,
    fts_doc_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    ensure_core_table(session)
    params: dict[str, Any] = {"course_id": course_id}
    type_clause = ""
    if document_types:
        placeholders = []
        for index, doc_type in enumerate(document_types):
            key = f"doc_type_{index}"
            params[key] = doc_type
            placeholders.append(f":{key}")
        type_clause = f" AND doc_type IN ({', '.join(placeholders)})"

    match_clauses = []
    for index, token in enumerate(tokens or []):
        key = f"term_{index}"
        params[key] = f"%{_escape_like_token(token)}%"
        match_clauses.append(
            f"(lower(title) LIKE :{key} ESCAPE '\\' OR lower(body) LIKE :{key} ESCAPE '\\')"
        )
    token_clause = ""
    if match_clauses:
        token_clause = " AND " + " AND ".join(match_clauses)

    fts_clause = ""
    if fts_doc_keys:
        placeholders = []
        for index, doc_key in enumerate(sorted(fts_doc_keys)):
            key = f"fts_doc_key_{index}"
            params[key] = doc_key
            placeholders.append(f":{key}")
        fts_clause = f" OR doc_key IN ({', '.join(placeholders)})"

    match_clause = f" AND ((1=1{token_clause}){fts_clause})" if token_clause or fts_clause else ""
    rows = session.execute(
        text(
            """
            SELECT doc_key, doc_type, course_id, section_id, asset_id, title, body,
                   order_index, source_page, source_heading, source_chapter, source_slide
            FROM search_documents
            WHERE course_id = :course_id
            """
            + type_clause
            + match_clause
        ),
        params,
    ).mappings()
    return [dict(row) for row in rows]
