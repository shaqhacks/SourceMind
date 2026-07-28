from __future__ import annotations

import pytest


def _first_section(client, course_id: str) -> dict:
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    return client.get(f"/api/sections/{sections[0]['id']}").json()


def test_selection_block_injected_before_excerpts(client, ingest_course, stub_provider):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section = _first_section(client, course_id)
    exact = section["body_md"][:40]

    resp = client.post(
        f"/api/courses/{course_id}/chat",
        json={
            "message": "explain this",
            "selection": {"section_id": section["id"], "exact": exact},
        },
    )
    assert resp.status_code == 200

    # The current turn is the LAST message of the LAST call's message list.
    sent = stub_provider.received_messages[-1][-1]["content"]
    assert "<selected_passage>" in sent
    assert exact in sent
    # Spec: selected passage comes AHEAD of the RAG excerpts.
    assert sent.index("<selected_passage>") < sent.index("<excerpts>")


def test_selection_section_of_other_course_is_422(client, ingest_course, stub_provider):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section = _first_section(client, course_id)
    other = client.post("/api/courses", json={"title": "Other"}).json()["id"]

    resp = client.post(
        f"/api/courses/{other}/chat",
        json={"message": "explain", "selection": {"section_id": section["id"], "exact": "x"}},
    )
    assert resp.status_code == 422
    # Rejected BEFORE any provider call — no spend, no turn persisted.
    assert stub_provider.call_count == 0
    assert client.get(f"/api/courses/{other}/chat").json() == []


def test_selection_exact_not_in_body_degrades_to_quote_alone(client, ingest_course, stub_provider):
    """A verbatim miss (stale/forged anchor, or just an exact that never
    occurs in this section's body_md) must never error — _build_selection_block
    falls back to `surrounding_source == exact` instead of the usual
    surrounding-body_md window (chat_service.py's idx==-1 branch)."""
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section = _first_section(client, course_id)
    exact = "this exact phrase does not occur anywhere in the section body"
    assert exact not in section["body_md"]

    resp = client.post(
        f"/api/courses/{course_id}/chat",
        json={
            "message": "explain this",
            "selection": {"section_id": section["id"], "exact": exact},
        },
    )
    assert resp.status_code == 200

    sent = stub_provider.received_messages[-1][-1]["content"]
    assert "<selected_passage>" in sent
    assert f"<selected_text>\n{exact}\n</selected_text>" in sent
    # Degraded: surrounding_source is the quote alone, not a window into
    # body_md (there is no match to center a window on).
    assert f"<surrounding_source>\n{exact}\n</surrounding_source>" in sent


@pytest.mark.parametrize("exact", ["", "x" * 2001])
def test_selection_exact_length_out_of_bounds_is_422(client, ingest_course, stub_provider, exact):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section = _first_section(client, course_id)

    resp = client.post(
        f"/api/courses/{course_id}/chat",
        json={"message": "explain this", "selection": {"section_id": section["id"], "exact": exact}},
    )
    assert resp.status_code == 422
    assert stub_provider.call_count == 0


def test_selection_unknown_section_id_is_422(client, ingest_course, stub_provider):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")

    resp = client.post(
        f"/api/courses/{course_id}/chat",
        json={
            "message": "explain this",
            "selection": {"section_id": "does-not-exist", "exact": "x"},
        },
    )
    assert resp.status_code == 422
    assert stub_provider.call_count == 0


def test_selection_stored_as_blockquote_in_history(client, ingest_course, stub_provider):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section = _first_section(client, course_id)
    exact = section["body_md"][:40]

    client.post(
        f"/api/courses/{course_id}/chat",
        json={
            "message": "explain this",
            "selection": {"section_id": section["id"], "exact": exact},
        },
    )
    history = client.get(f"/api/courses/{course_id}/chat").json()
    user_turns = [t for t in history if t["role"] == "user"]
    assert user_turns[-1]["content"].startswith("> ")
    assert "explain this" in user_turns[-1]["content"]


def _surrounding_source(block: str) -> str:
    start_tag = "<surrounding_source>\n"
    end_tag = "\n</surrounding_source>"
    start = block.index(start_tag) + len(start_tag)
    end = block.index(end_tag)
    return block[start:end]


def test_selection_context_window_clamped_to_max_chars_each_side():
    """_build_selection_block's surrounding_source window is capped at
    _SELECTION_CONTEXT_CHARS on each side of the match -- assert the exact
    boundaries/length, not just that some surrounding text is present."""
    from app.db.models import Section
    from app.services.chat_service import _SELECTION_CONTEXT_CHARS, _build_selection_block

    exact = "TARGET PASSAGE"
    before = "b" * 5000
    after = "a" * 5000
    body = before + exact + after
    section = Section(
        id="s1", course_id="c1", order_index=0, title="Sec", body_md=body, content_hash="h"
    )

    block = _build_selection_block(section, exact)
    surrounding = _surrounding_source(block)

    idx = body.find(exact)
    expected = body[idx - _SELECTION_CONTEXT_CHARS : idx + len(exact) + _SELECTION_CONTEXT_CHARS]
    assert surrounding == expected
    assert len(surrounding) == _SELECTION_CONTEXT_CHARS * 2 + len(exact)


def test_selection_context_window_left_clamped_at_zero_near_start():
    """When the match is close enough to the start of body_md that a full
    _SELECTION_CONTEXT_CHARS window would go negative, the left edge must
    clamp at 0 instead of wrapping/erroring."""
    from app.db.models import Section
    from app.services.chat_service import _SELECTION_CONTEXT_CHARS, _build_selection_block

    exact = "TARGET PASSAGE"
    body = exact + "a" * 5000  # match starts at index 0 -- no room to the left
    section = Section(
        id="s1", course_id="c1", order_index=0, title="Sec", body_md=body, content_hash="h"
    )

    block = _build_selection_block(section, exact)
    surrounding = _surrounding_source(block)

    expected = body[: len(exact) + _SELECTION_CONTEXT_CHARS]
    assert surrounding == expected
    assert len(surrounding) == len(exact) + _SELECTION_CONTEXT_CHARS
    assert surrounding.startswith(exact)
