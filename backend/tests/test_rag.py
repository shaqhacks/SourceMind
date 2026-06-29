"""RAG (course-level grounded cited chat) tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from SourceMind.backend.db import base, models
from SourceMind.backend.main import app
from SourceMind.backend.routers.library import provider_dependency


class StubProvider:
    """Minimal LLM stub that returns a deterministic canned answer."""

    def complete(self, prompt: str, *, system: str = "", schema=None, max_tokens: int = 4096) -> str:
        return "Grounded answer citing [1]."


@pytest.fixture()
def client():
    app.dependency_overrides[provider_dependency] = lambda: StubProvider()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(provider_dependency, None)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    """Isolate every test in its own tmp SQLite database; clean up on teardown."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SOURCEMIND_ASSETS_DIR", str(tmp_path / "data"))
    base.init_db()
    yield
    base.reset_engine_cache()


# ---------------------------------------------------------------------------
# Task 2 — embeddings, chunking, retrieval
# ---------------------------------------------------------------------------

def test_chunk_pages_overlap():
    from SourceMind.backend.extract.pdf import ExtractedPage
    from SourceMind.backend.pipeline.chunk import chunk_pages

    # Uniquely-numbered words so overlap content can be verified precisely.
    page1 = ExtractedPage(page_number=1, text=" ".join(f"w{i}" for i in range(1, 201)))
    page2 = ExtractedPage(page_number=2, text=" ".join(f"w{i}" for i in range(201, 401)))
    empty_page = ExtractedPage(page_number=3, text="   ")

    # target=150, overlap=50, step=100 → windows at 0,100,200,300 → 4 chunks.
    chunks = chunk_pages([page1, page2, empty_page], target_words=150, overlap_words=50)

    # Empty page must be skipped → 400 total words (not 401).
    assert len(chunks) == 4

    # Every non-final chunk must have exactly target_words words.
    for source_ref, content in chunks[:-1]:
        assert len(content.split()) == 150

    # Consecutive chunks share exactly overlap_words trailing/leading words.
    for i in range(len(chunks) - 1):
        c0_words = chunks[i][1].split()
        c1_words = chunks[i + 1][1].split()
        assert c0_words[-50:] == c1_words[:50]

    # Both source_ref formats appear; verify exact strings.
    refs = [sr for sr, _ in chunks]
    assert refs[0] == "p.1"       # chunk 0 lives entirely on page 1
    assert refs[1] == "pp.1-2"    # chunk 1 crosses the page boundary
    assert "p.1" in refs
    assert "pp.1-2" in refs


def test_cosine():
    from SourceMind.backend.pipeline.retrieve import cosine

    assert cosine([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert cosine([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)
    assert cosine([0, 0, 0], [1, 0, 0]) == 0.0  # zero-norm guard


def test_retrieve_ranks_by_similarity():
    from SourceMind.backend.pipeline.retrieve import retrieve

    with base.get_session() as session:
        session.add(models.Course(id="c1", title="T"))
        session.add(models.Chunk(
            course_id="c1", source_ref="p.1", content="alpha",
            embedding=[1, 0, 0], chunk_index=0,
        ))
        session.add(models.Chunk(
            course_id="c1", source_ref="p.2", content="beta",
            embedding=[0, 1, 0], chunk_index=1,
        ))
        session.add(models.Chunk(
            course_id="c1", source_ref="p.3", content="gamma",
            embedding=[0, 0, 1], chunk_index=2,
        ))

    with base.get_session() as session:
        results = retrieve(session, "c1", "q", k=2, query_embedding=[0.9, 0.1, 0.0])
        assert len(results) == 2
        assert results[0]["source_ref"] == "p.1"
        # Scores must be in descending order.
        assert results[0]["score"] >= results[1]["score"]
        # Missing course returns empty list; no embed/network call made.
        empty = retrieve(session, "missing_course", "q", query_embedding=[1, 0, 0])
        assert empty == []


def test_chunk_and_chat_citations_persist():
    with base.get_session() as session:
        session.add(models.Course(id="c1", title="T"))
        session.add(
            models.Chunk(
                course_id="c1",
                source_ref="p.1",
                content="hello",
                embedding=[0.1, 0.2],
                chunk_index=0,
            )
        )
        session.add(
            models.ChatTurn(
                course_id="c1",
                section_id="__course__",
                role="assistant",
                content="ans",
                citations=[{"source_ref": "p.1", "content": "hello"}],
                created_at="2026-01-01",
            )
        )

    with base.get_session() as session:
        chunk = session.query(models.Chunk).filter_by(course_id="c1").one()
        assert chunk.embedding == [0.1, 0.2]
        assert chunk.chunk_index == 0

        turn = session.query(models.ChatTurn).filter_by(course_id="c1").one()
        assert turn.citations == [{"source_ref": "p.1", "content": "hello"}]


# ---------------------------------------------------------------------------
# Task 4 — course-level grounded cited chat + history endpoints
# ---------------------------------------------------------------------------

def test_chat_endpoint_grounded_and_cited(client, monkeypatch):
    # Stub embed_text so no Ollama/network call is made.
    monkeypatch.setattr(
        "SourceMind.backend.pipeline.retrieve.embed_text",
        lambda text: [1.0, 0.0, 0.0],
    )

    # Seed a Course + 2 Chunk rows with hand-set embeddings.
    with base.get_session() as session:
        session.add(models.Course(id="c1", title="T"))
        session.add(models.Chunk(
            course_id="c1",
            source_ref="p.42",
            content="Close chunk — should rank first.",
            embedding=[1.0, 0.0, 0.0],
            chunk_index=0,
        ))
        session.add(models.Chunk(
            course_id="c1",
            source_ref="p.99",
            content="Distant chunk.",
            embedding=[0.0, 1.0, 0.0],
            chunk_index=1,
        ))

    # POST /library/courses/c1/chat — happy path
    resp = client.post("/library/courses/c1/chat", json={"question": "What is X?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"]  # non-empty
    assert data["citations"]  # non-empty
    for cit in data["citations"]:
        assert "source_ref" in cit
        assert "content" in cit
        assert "score" not in cit  # score must be dropped

    # Exactly two ChatTurn rows with section_id == "__course__" persisted.
    with base.get_session() as session:
        turns = (
            session.query(models.ChatTurn)
            .filter_by(course_id="c1", section_id="__course__")
            .order_by(models.ChatTurn.created_at)
            .all()
        )
        assert len(turns) == 2
        turn_data = [
            {"role": t.role, "citations": t.citations}
            for t in turns
        ]
    user_turn = next(t for t in turn_data if t["role"] == "user")
    asst_turn = next(t for t in turn_data if t["role"] == "assistant")
    assert user_turn["citations"] is None
    assert asst_turn["citations"]  # non-empty

    # GET /library/courses/c1/chat/history — returns turns in order with citations.
    hist_resp = client.get("/library/courses/c1/chat/history")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    history = hist_data["history"]
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    asst_hist = history[1]
    assert asst_hist["citations"]
    for cit in asst_hist["citations"]:
        assert "source_ref" in cit
        assert "content" in cit

    # POST to a missing course → 404.
    miss = client.post("/library/courses/missing/chat", json={"question": "Q?"})
    assert miss.status_code == 404
