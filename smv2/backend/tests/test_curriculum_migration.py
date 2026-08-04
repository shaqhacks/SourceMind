from __future__ import annotations

import sqlite3

from alembic import command

from app.db.engine import dispose_engine
from app.db.init import _alembic_config


def test_legacy_concept_graph_becomes_unverified_published_curriculum(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "legacy-curriculum.db"
    monkeypatch.setenv("SMV2_DB_URL", f"sqlite:///{db_path}")
    dispose_engine()
    command.upgrade(_alembic_config(), "0014_learner_profiles")

    connection = sqlite3.connect(db_path)
    try:
        now = "2026-08-02 12:00:00"
        connection.execute(
            "INSERT INTO courses (id, title, status, created_at, updated_at) "
            "VALUES ('course', 'Legacy curriculum', 'ready', ?, ?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO sections "
            "(id, course_id, order_index, title, page_start, page_end, body_md, "
            "content_hash, lesson_md, lesson_status, lesson_model, lesson_prompt_version, "
            "extractor_version, created_at, updated_at, kind, chapter_label, asset_id) "
            "VALUES ('section', 'course', 0, 'Foundations', 0, 0, 'Source excerpt', "
            "'source-hash', NULL, 'none', NULL, NULL, NULL, ?, ?, 'content', "
            "'Chapter 1', NULL)",
            (now, now),
        )
        for concept_id, slug, label in (
            ("concept-a", "fractions", "Fractions"),
            ("concept-b", "equivalence", "Equivalent fractions"),
        ):
            connection.execute(
                "INSERT INTO concepts "
                "(id, course_id, slug, label, chapter_label, section_id, created_at, updated_at) "
                "VALUES (?, 'course', ?, ?, 'Chapter 1', 'section', ?, ?)",
                (concept_id, slug, label, now, now),
            )
        connection.execute(
            "INSERT INTO concept_edges "
            "(id, course_id, from_concept_id, to_concept_id, created_at) "
            "VALUES ('edge', 'course', 'concept-a', 'concept-b', ?)",
            (now,),
        )
        connection.execute(
            "INSERT INTO concept_section_links "
            "(id, course_id, concept_id, section_id, rank, relevance_md, created_at) "
            "VALUES ('link', 'course', 'concept-a', 'section', 0, 'Introduced here', ?)",
            (now,),
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(_alembic_config(), "0015_versioned_curriculum")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        version = connection.execute("SELECT * FROM curriculum_versions").fetchone()
        assert version["status"] == "published"
        assert version["is_current"] == 1
        assert connection.execute("SELECT COUNT(*) FROM concept_revisions").fetchone()[0] == 2
        relation = connection.execute("SELECT * FROM concept_relations").fetchone()
        assert relation["kind"] == "requires"
        assert relation["review_state"] == "unverified"
        sources = connection.execute("SELECT * FROM concept_source_links").fetchall()
        assert {source["concept_id"] for source in sources} == {"concept-a", "concept-b"}
        assert all(source["source_content_hash"] == "source-hash" for source in sources)
    finally:
        connection.close()
        dispose_engine()
