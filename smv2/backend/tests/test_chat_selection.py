from __future__ import annotations


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
