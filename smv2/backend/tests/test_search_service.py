from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.engine import get_session
from app.db.models import Asset, Course, Highlight, Note, Section


def _seed_course(
    course_id: str = "course-search",
    *,
    title: str = "Search Course",
    section_bodies: list[tuple[str, str, str]] | None = None,
) -> str:
    from app.services import search_index

    session = get_session()
    try:
        session.add(Course(id=course_id, title=title, status="ready"))
        session.flush()
        asset_id = f"asset-{course_id}"
        session.add(
            Asset(
                id=asset_id,
                course_id=course_id,
                filename=f"{course_id}.pdf",
                content_type="application/pdf",
                size_bytes=1,
                sha256=f"sha-{course_id}",
                stored_path=f"/tmp/{course_id}.pdf",
                status="extracted",
            )
        )
        session.flush()
        for order_index, (section_id, section_title, body_md) in enumerate(
            section_bodies
            or [
                ("section-beta-title", "Beta", "alpha alpha supporting text"),
                ("section-alpha-title", "Alpha Title", "alpha supporting text"),
                ("section-gamma", "Gamma", "nothing relevant"),
            ]
        ):
            section = Section(
                id=section_id,
                course_id=course_id,
                order_index=order_index,
                title=section_title,
                asset_id=asset_id,
                page_start=order_index,
                page_end=order_index,
                body_md=body_md,
                content_hash=f"hash-{section_id}",
                lesson_md=None,
                lesson_status="none",
            )
            session.add(section)
            session.flush()
            search_index.upsert_section_document(session, section)
        session.commit()
        return course_id
    finally:
        session.close()


def _result_ids(results) -> list[str]:
    return [item.section_id for item in results.items]


def test_exact_title_match_is_boosted_over_body_frequency(client):
    from app.services import search_service

    course_id = _seed_course()

    results = search_service.search_course(course_id, "alpha")

    assert _result_ids(results)[:2] == ["section-alpha-title", "section-beta-title"]
    assert results.items[0].score > results.items[1].score


def test_query_normalization_escapes_like_wildcards_once(client):
    from app.services import search_service

    course_id = _seed_course(
        "course-wildcards",
        section_bodies=[
            ("literal", "Literal Symbols", r"Discount code is 100%_real\deal."),
            ("broad", "Broad", "1000 unrelated real deal terms"),
        ],
    )

    results = search_service.search_course(course_id, r"  100%_real\deal  ")

    assert _result_ids(results) == ["literal"]


def test_equal_score_ordering_and_cursor_pagination_are_stable(client, monkeypatch):
    from app.services import search_index, search_service

    monkeypatch.setattr(search_index, "ensure_search_backend", lambda session: "like")
    course_id = _seed_course(
        "course-cursor",
        section_bodies=[
            ("s2", "Same", "alpha"),
            ("s1", "Same", "alpha"),
            ("s3", "Same", "alpha"),
        ],
    )

    first_page = search_service.search_course(course_id, "alpha", limit=2)
    second_page = search_service.search_course(course_id, "alpha", limit=2, cursor=first_page.next_cursor)

    assert _result_ids(first_page) == ["s1", "s2"]
    assert _result_ids(second_page) == ["s3"]
    assert {item.cursor_token for item in first_page.items}.isdisjoint(
        {item.cursor_token for item in second_page.items}
    )
    assert second_page.next_cursor is None


@pytest.mark.parametrize("cursor", ["not-a-token", "W10=", "eyJub3QiOiJhLWxpc3QifQ=="])
def test_malformed_cursor_raises_value_error_instead_of_restart(client, cursor):
    from app.services import search_service

    course_id = _seed_course("course-bad-cursor")

    with pytest.raises(ValueError, match="invalid cursor"):
        search_service.search_course(course_id, "alpha", cursor=cursor)


def test_fts5_backend_is_used_when_available(client):
    from app.services import search_index, search_service

    course_id = _seed_course("course-fts", section_bodies=[("fts-section", "Needle", "rareword")])

    results = search_service.search_course(course_id, "rareword")

    assert results.backend == search_index.ensure_search_backend(get_session())
    assert _result_ids(results) == ["fts-section"]


def test_fts5_transition_populates_historical_like_rows(client, monkeypatch):
    from app.services import search_index, search_service

    monkeypatch.setattr(search_index, "fts5_available", lambda session: False)
    course_id = _seed_course(
        "course-transition",
        section_bodies=[("transition-section", "Transition", "historicalword")],
    )
    assert search_service.search_course(course_id, "historicalword").backend == "like"

    monkeypatch.setattr(search_index, "fts5_available", lambda session: True)
    session = get_session()
    try:
        assert search_index.ensure_search_backend(session) == "fts5"
        fts_keys = search_index.matching_fts_doc_keys(session, course_id, "historicalword")
        assert fts_keys == {"section:transition-section"}
    finally:
        session.close()

    results = search_service.search_course(course_id, "historicalword")
    assert results.backend == "fts5"
    assert _result_ids(results) == ["transition-section"]


def test_fts5_enablement_handles_empty_search_documents(client):
    from app.services import search_index

    session = get_session()
    try:
        assert search_index.ensure_search_backend(session) in {"fts5", "like"}
        if search_index.fts5_available(session):
            assert search_index.matching_fts_doc_keys(session, "missing-course", "anything") == set()
    finally:
        session.close()


def test_like_fallback_is_used_when_fts5_is_unavailable(client, monkeypatch):
    from app.services import search_index, search_service

    monkeypatch.setattr(search_index, "fts5_available", lambda session: False)
    course_id = _seed_course("course-like", section_bodies=[("like-section", "Needle", "fallbackword")])

    results = search_service.search_course(course_id, "fallbackword")

    assert results.backend == "like"
    assert _result_ids(results) == ["like-section"]


def test_excerpts_are_sanitized_and_do_not_preserve_raw_html(client):
    from app.services import search_service

    course_id = _seed_course(
        "course-html",
        section_bodies=[("html-section", "Unsafe", "alpha <script>alert(1)</script> <b>keep</b>")],
    )

    [item] = search_service.search_course(course_id, "alpha").items

    assert item.excerpt_md
    assert "<script>" not in item.excerpt_md
    assert "&lt;script&gt;" in item.excerpt_md
    assert "<b>" not in item.excerpt_md


def test_rebuild_reflects_reingest_lesson_note_and_highlight_lifecycle(client):
    from app.services import search_index, search_service

    course_id = _seed_course(
        "course-rebuild",
        section_bodies=[("section-one", "Original", "alpha source text")],
    )
    session = get_session()
    try:
        section = session.get(Section, "section-one")
        assert section is not None
        section.lesson_md = "lessonword generated lesson"
        search_index.upsert_lesson_document(session, section)
        note = Note(
            id="note-one",
            course_id=course_id,
            section_id=section.id,
            page=0,
            anchor_y=0.5,
            note_md="noteword first",
        )
        highlight = Highlight(
            id="highlight-one",
            course_id=course_id,
            section_id=section.id,
            exact="source",
            prefix="",
            suffix="",
            occurrence=0,
            page=0,
            color="yellow",
            surface="source",
            note_md="highlightword first",
            created_at=datetime.now(timezone.utc) + timedelta(seconds=1),
        )
        session.add_all([note, highlight])
        session.flush()
        search_index.upsert_note_document(session, note)
        search_index.upsert_highlight_document(session, highlight)
        session.commit()
    finally:
        session.close()

    assert search_service.search_course(course_id, "lessonword").items[0].doc_type == "lesson"
    assert search_service.search_course(course_id, "noteword").items[0].doc_type == "note"
    assert search_service.search_course(course_id, "highlightword").items[0].doc_type == "highlight"

    session = get_session()
    try:
        note = session.get(Note, "note-one")
        highlight = session.get(Highlight, "highlight-one")
        assert note is not None and highlight is not None
        note.note_md = "editednoteword"
        search_index.upsert_note_document(session, note)
        search_index.delete_highlight_document(session, highlight.id)
        session.delete(highlight)
        section = session.get(Section, "section-one")
        assert section is not None
        section.lesson_md = "regeneratedlessonword"
        search_index.upsert_lesson_document(session, section)
        session.commit()
    finally:
        session.close()

    assert search_service.search_course(course_id, "highlightword").items == []
    assert search_service.search_course(course_id, "editednoteword").items[0].doc_type == "note"
    assert search_service.search_course(course_id, "regeneratedlessonword").items[0].doc_type == "lesson"

    rebuilt = search_service.rebuild_course_index(course_id)
    assert rebuilt == 3
    assert search_service.search_course(course_id, "editednoteword").items[0].doc_type == "note"
