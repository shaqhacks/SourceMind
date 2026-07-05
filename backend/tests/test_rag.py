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
    assert refs[2] == "p.2"       # chunk 2 lives entirely on page 2
    assert refs[3] == "p.2"       # chunk 3 lives entirely on page 2
    assert "p.1" in refs
    assert "pp.1-2" in refs


def test_chunk_pages_defaults_come_from_config(monkeypatch):
    """target_words/overlap_words fall back to config.py env tunables when
    not passed explicitly."""
    from SourceMind.backend.extract.pdf import ExtractedPage
    from SourceMind.backend.pipeline.chunk import chunk_pages

    monkeypatch.setenv("SOURCEMIND_CHUNK_TARGET_WORDS", "100")
    monkeypatch.setenv("SOURCEMIND_CHUNK_OVERLAP_WORDS", "20")

    page = ExtractedPage(page_number=1, text=" ".join(f"w{i}" for i in range(300)))
    chunks = chunk_pages([page])  # no explicit target/overlap

    # step = 100 - 20 = 80; windows at 0,80,160,240 -> 4 chunks (last partial).
    assert len(chunks) == 4
    for _, content in chunks[:-1]:
        assert len(content.split()) == 100


def test_chunk_pages_section_aware_prefixes_source_ref():
    """With sections given, a chunk never straddles two chapters, and its
    source_ref is prefixed with the owning section_id."""
    from SourceMind.backend.extract.pdf import ExtractedPage
    from SourceMind.backend.pipeline.chunk import chunk_pages

    pages = [
        ExtractedPage(page_number=0, text=" ".join(f"a{i}" for i in range(60))),
        ExtractedPage(page_number=1, text=" ".join(f"b{i}" for i in range(60))),
        ExtractedPage(page_number=2, text=" ".join(f"c{i}" for i in range(60))),
        ExtractedPage(page_number=3, text=" ".join(f"d{i}" for i in range(60))),
    ]
    sections = [
        {"section_id": "ch1", "page_start": 0, "page_end": 1},
        {"section_id": "ch2", "page_start": 2, "page_end": 3},
    ]

    chunks = chunk_pages(pages, target_words=200, overlap_words=0, sections=sections)

    refs = [sr for sr, _ in chunks]
    assert all(r.startswith("ch1:") or r.startswith("ch2:") for r in refs)
    # ch1's chunk(s) only ever contain words from pages 0-1; ch2's only 2-3 —
    # i.e. no chunk mixes content across the section boundary.
    for source_ref, content in chunks:
        words = content.split()
        if source_ref.startswith("ch1:"):
            assert all(w.startswith("a") or w.startswith("b") for w in words)
        else:
            assert all(w.startswith("c") or w.startswith("d") for w in words)


def test_chunk_pages_section_aware_covers_leftover_pages():
    """Pages outside every section's range still get chunked (whole-document
    fallback ref format), so content isn't silently dropped."""
    from SourceMind.backend.extract.pdf import ExtractedPage
    from SourceMind.backend.pipeline.chunk import chunk_pages

    pages = [
        ExtractedPage(page_number=0, text="front matter preface text"),
        ExtractedPage(page_number=1, text=" ".join(f"w{i}" for i in range(60))),
    ]
    # Only page 1 belongs to a section; page 0 (front matter) is uncovered.
    sections = [{"section_id": "ch1", "page_start": 1, "page_end": 1}]

    chunks = chunk_pages(pages, target_words=200, overlap_words=0, sections=sections)

    refs = [sr for sr, _ in chunks]
    assert any(r.startswith("ch1:") for r in refs)
    assert any(not r.startswith("ch1:") for r in refs)  # leftover page 0, old-format ref
    all_content = " ".join(c for _, c in chunks)
    assert "preface" in all_content  # nothing dropped


def test_chunk_pages_no_sections_uses_fallback_format():
    """Empty/None sections keep the original (non-prefixed) ref format."""
    from SourceMind.backend.extract.pdf import ExtractedPage
    from SourceMind.backend.pipeline.chunk import chunk_pages

    page = ExtractedPage(page_number=5, text="hello world")
    assert chunk_pages([page], sections=None)[0][0] == "p.5"
    assert chunk_pages([page], sections=[])[0][0] == "p.5"


def test_cosine():
    from SourceMind.backend.pipeline.retrieve import cosine

    assert cosine([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert cosine([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)
    assert cosine([0, 0, 0], [1, 0, 0]) == 0.0  # zero-norm guard


def test_cosine_batch_matches_pure_python_cosine():
    """The vectorized (numpy) batch scorer must agree with cosine() per-row,
    including its zero-norm guard for an all-zero embedding."""
    from SourceMind.backend.pipeline.retrieve import _cosine_batch, cosine

    query = [0.9, 0.1, 0.0]
    embeddings = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]]

    batch_scores = _cosine_batch(query, embeddings)
    expected = [cosine(query, e) for e in embeddings]

    assert batch_scores == pytest.approx(expected)
    assert batch_scores[-1] == 0.0  # zero-norm row


def test_cosine_batch_falls_back_without_numpy(monkeypatch):
    """When numpy isn't available, _cosine_batch still scores correctly via
    the pure-Python per-row path."""
    from SourceMind.backend.pipeline import retrieve as retrieve_mod

    monkeypatch.setattr(retrieve_mod, "np", None)
    query = [1, 0, 0]
    embeddings = [[1, 0, 0], [0, 1, 0]]

    scores = retrieve_mod._cosine_batch(query, embeddings)

    assert scores == pytest.approx([1.0, 0.0])


def test_cosine_batch_falls_back_on_ragged_embeddings():
    """Mismatched embedding dimensions can't be stacked into a rectangular
    numpy matrix — falls back to the pure-Python per-row path instead of
    raising."""
    from SourceMind.backend.pipeline.retrieve import _cosine_batch

    query = [1, 0, 0]
    embeddings = [[1, 0, 0], [1, 0]]  # second row has the wrong dimension

    scores = _cosine_batch(query, embeddings)

    assert scores[0] == pytest.approx(1.0)


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


def test_index_course_inserts_chunks_and_is_idempotent(monkeypatch):
    from SourceMind.backend.extract.pdf import ExtractedPage
    from SourceMind.backend.pipeline.service import (
        _save_pages,
        course_assets_dir,
        index_course,
    )

    course_id = "test_index_c"
    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.embed_texts",
        lambda texts: [[float(len(t)), 0.0] for t in texts],
    )

    # Seed the Course row first (FK constraint).
    with base.get_session() as session:
        session.add(models.Course(id=course_id, title="T"))

    # Write pages.json with enough words to yield at least one chunk.
    assets_dir = course_assets_dir(course_id)
    assets_dir.mkdir(parents=True, exist_ok=True)
    pages = [
        ExtractedPage(
            page_number=1,
            text=" ".join(f"word{i}" for i in range(50)),
        )
    ]
    _save_pages(pages, assets_dir)

    # First call — creates chunks.
    index_course(course_id)

    with base.get_session() as session:
        chunks = (
            session.query(models.Chunk)
            .filter_by(course_id=course_id)
            .order_by(models.Chunk.chunk_index)
            .all()
        )
        assert len(chunks) >= 1
        first_count = len(chunks)

        # chunk_index values are 0..n-1 in insertion order.
        for expected_i, chunk in enumerate(chunks):
            assert chunk.chunk_index == expected_i

        # Each chunk has a non-empty embedding list.
        for chunk in chunks:
            assert chunk.embedding and len(chunk.embedding) > 0

        # source_ref and content are populated.
        for chunk in chunks:
            assert chunk.source_ref
            assert chunk.content

    # Second call — must be idempotent (delete-then-insert, no duplication).
    index_course(course_id)

    with base.get_session() as session:
        second_count = (
            session.query(models.Chunk)
            .filter_by(course_id=course_id)
            .count()
        )
    assert second_count == first_count


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
