"""ORM model roundtrip tests — Task 2."""

import pytest
from SourceMind.backend.db import base


@pytest.fixture(autouse=True)
def _reset_engine_cache():
    """Dispose cached engines after each test to prevent ResourceWarning."""
    yield
    base.reset_engine_cache()


def test_course_chapter_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{tmp_path / 't.db'}")
    from SourceMind.backend.db import base, models
    base.init_db(base.make_engine())
    with base.get_session() as s:
        s.add(models.Course(id="algebra", title="Algebra", status="ready"))
        s.add(models.Chapter(course_id="algebra", section_id="1-2", title="Integers",
                             body_md="# x", quiz=[{"q": "?", "options": ["a"], "answer": 0, "explain": "e"}],
                             cards=[], objectives=["o"], importance="core",
                             source_pages=[1, 2], assets=[], word_count=3, status="ready"))
    with base.get_session() as s:
        ch = s.query(models.Chapter).filter_by(course_id="algebra").one()
        assert ch.quiz[0]["answer"] == 0
