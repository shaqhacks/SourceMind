from __future__ import annotations

from app.pipeline.retrieval import _cosine_similarity, _lexical_score, _tokenize, rank_chunks, score_chunks


class _FakeChunk:
    def __init__(self, id, text, embedding=None, section_id="sec-1", source_ref="sec-1:p.1", page=1):
        self.id = id
        self.text = text
        self.embedding = embedding
        self.section_id = section_id
        self.source_ref = source_ref
        self.page = page


def test_tokenize_lowercases_and_splits_alnum():
    assert _tokenize("Hello, World! 123") == ["hello", "world", "123"]


def test_lexical_score_perfect_overlap():
    from collections import Counter

    q = Counter(_tokenize("photosynthesis process"))
    c = Counter(_tokenize("the photosynthesis process converts light"))
    assert _lexical_score(q, c) == 1.0


def test_lexical_score_zero_when_no_overlap():
    from collections import Counter

    q = Counter(_tokenize("photosynthesis"))
    c = Counter(_tokenize("gravity and motion"))
    assert _lexical_score(q, c) == 0.0


def test_cosine_similarity_identical_vectors_is_one():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_mismatched_dimensions_returns_zero_not_raise():
    """A chunk embedded under a different embedding model/dimensionality
    than the current query must degrade to 0.0 (lexical-only for that
    chunk), not raise and take down the whole ranking.
    """
    assert _cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0]) == 0.0


def test_score_chunks_handles_mismatched_embedding_dimensions_without_raising():
    chunks = [
        _FakeChunk("c1", "photosynthesis converts light to energy", embedding=[1.0, 0.0, 0.0]),
        _FakeChunk("c2", "photosynthesis converts light to energy", embedding=[1.0, 0.0]),  # different dims
    ]
    ranked = score_chunks(chunks, "photosynthesis energy", [1.0, 0.0, 0.0], k=10)
    assert len(ranked) == 2


def test_retrieval_skips_null_embeddings():
    """Chunks with a NULL embedding must never crash the vector path and
    must never be silently excluded — they still get scored (falling back
    to lexical-only for that one chunk) while chunks WITH embeddings still
    get the full hybrid vector+lexical score.
    """
    chunks = [
        _FakeChunk("c1", "the mitochondria is the powerhouse of the cell", embedding=[1.0, 0.0, 0.0]),
        _FakeChunk("c2", "the mitochondria is the powerhouse of the cell", embedding=None),
        _FakeChunk("c3", "completely unrelated text about volcanoes", embedding=[0.0, 1.0, 0.0]),
    ]
    query_embedding = [1.0, 0.0, 0.0]
    # A partial lexical match (query has terms the chunks don't) keeps the
    # lexical score below 1.0, so the vector term can actually differentiate
    # c1 (has an embedding) from c2 (same text, no embedding) instead of both
    # capping out at a tied 1.0.
    ranked = score_chunks(chunks, "mitochondria powerhouse cell energy production", query_embedding, k=10)

    assert len(ranked) == 3
    scores_by_id = {rc.chunk.id: rc.score for rc in ranked}
    # c2 has identical text to c1 but no embedding: it should still score
    # (lexical component only), not be dropped, and not error out.
    assert scores_by_id["c2"] > 0.0
    # c1 (embedding + lexical match) outranks c2 (lexical-only, same text).
    assert scores_by_id["c1"] > scores_by_id["c2"]
    # c3 (no lexical or vector match) scores lowest.
    assert scores_by_id["c3"] < scores_by_id["c2"]


def test_score_chunks_falls_back_to_lexical_only_when_query_embedding_none():
    chunks = [
        _FakeChunk("c1", "photosynthesis converts light to energy", embedding=[1.0, 0.0]),
        _FakeChunk("c2", "totally unrelated volcano text", embedding=[0.0, 1.0]),
    ]
    ranked = score_chunks(chunks, "photosynthesis energy", None, k=10)
    scores_by_id = {rc.chunk.id: rc.score for rc in ranked}
    assert scores_by_id["c1"] > scores_by_id["c2"]
    assert scores_by_id["c1"] <= 1.0  # lexical-only score, never inflated by a phantom vector term


def test_score_chunks_respects_k():
    chunks = [_FakeChunk(f"c{i}", f"word{i} query", embedding=None) for i in range(10)]
    ranked = score_chunks(chunks, "query", None, k=3)
    assert len(ranked) == 3


def test_rank_chunks_empty_course_returns_empty(client):
    from app.db.engine import get_session

    session = get_session()
    try:
        result = rank_chunks(session, "no-such-course", "anything", k=6)
        assert result == []
    finally:
        session.close()


def test_rank_chunks_degrades_to_lexical_when_provider_raises(client, ingest_course, stub_provider):
    from app.llm.provider import NotSupportedError

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.embed_exception = NotSupportedError("no embeddings here")

    from app.db.engine import get_session

    session = get_session()
    try:
        result = rank_chunks(session, course_id, "chapter", k=6)
        # Must not raise, and must still return chunks ranked lexically.
        assert isinstance(result, list)
    finally:
        session.close()
