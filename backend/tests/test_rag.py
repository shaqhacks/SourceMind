"""RAG (course-level grounded cited chat) tests."""
from __future__ import annotations

import pytest

from SourceMind.backend.db import base, models


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    """Isolate every test in its own tmp SQLite database; clean up on teardown."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SOURCEMIND_ASSETS_DIR", str(tmp_path / "data"))
    base.init_db()
    yield
    base.reset_engine_cache()


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
