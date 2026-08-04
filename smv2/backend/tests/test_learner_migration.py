from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command

from app.db.engine import dispose_engine
from app.db.init import _alembic_config
from app.services.learner_context import LEGACY_LOCAL_LEARNER_ID


_NOW = "2026-08-02 12:00:00"


def _upgrade_to_0013(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SMV2_DB_URL", f"sqlite:///{db_path}")
    dispose_engine()
    command.upgrade(_alembic_config(), "0013_concept_graph")


def _seed_legacy_course(
    db_path: Path, learner_keys: list[str], *, include_global_history: bool
) -> str:
    course_id = "legacy-course"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO courses (id, title, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (course_id, "Legacy course", "ready", _NOW, _NOW),
        )
        for index, learner_key in enumerate(learner_keys):
            connection.execute(
                "INSERT INTO practice_answers "
                "(id, course_id, question_id, learner_key, selected_index, correct, "
                "points_delta, answered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"answer-{index}",
                    course_id,
                    f"question-{index}",
                    learner_key,
                    0,
                    1,
                    1,
                    _NOW,
                ),
            )
        if include_global_history:
            connection.execute(
                "INSERT INTO review_states "
                "(card_id, course_id, due_at, interval_days, ease, reps, lapses, "
                "last_grade, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("legacy-card", course_id, _NOW, 3.0, 2.5, 2, 0, 3, _NOW),
            )
            connection.execute(
                "INSERT INTO review_logs "
                "(id, card_id, course_id, graded_at, grade, elapsed_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("legacy-log", "legacy-card", course_id, _NOW, 3, 1200),
            )
            connection.execute(
                "INSERT INTO test_attempts "
                "(id, course_id, score, created_at, test_id, answers, results) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-attempt",
                    course_id,
                    0.5,
                    _NOW,
                    "legacy-test",
                    "[0]",
                    "[]",
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return course_id


def _upgrade_to_0014() -> None:
    command.upgrade(_alembic_config(), "0014_learner_profiles")


def _rows(db_path: Path, query: str) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def _canonical_learner_id(learner_key: str) -> str:
    try:
        return str(uuid.UUID(learner_key))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sourcemind:learner:{learner_key}"))


def test_learner_profile_migration_handles_empty_database(tmp_path, monkeypatch):
    db_path = tmp_path / "empty-legacy.db"
    _upgrade_to_0013(db_path, monkeypatch)

    _upgrade_to_0014()

    assert _rows(db_path, "SELECT * FROM learner_profiles") == []
    assert _rows(db_path, "SELECT * FROM course_learning_profiles") == []
    assert {
        row["name"] for row in _rows(db_path, "PRAGMA table_info(review_states)")
    } >= {"course_learning_profile_id", "card_id"}


def test_single_practice_learner_receives_legacy_course_history(tmp_path, monkeypatch):
    db_path = tmp_path / "single-learner-legacy.db"
    _upgrade_to_0013(db_path, monkeypatch)
    course_id = _seed_legacy_course(db_path, ["alice"], include_global_history=True)

    _upgrade_to_0014()

    learner_id = _canonical_learner_id("alice")
    profiles = _rows(
        db_path,
        "SELECT id, learner_id, course_id FROM course_learning_profiles",
    )
    assert [(row["learner_id"], row["course_id"]) for row in profiles] == [
        (learner_id, course_id)
    ]
    profile_id = profiles[0]["id"]
    assert _rows(db_path, "SELECT course_learning_profile_id FROM review_states")[0][0] == profile_id
    assert _rows(db_path, "SELECT course_learning_profile_id FROM review_logs")[0][0] == profile_id
    assert _rows(db_path, "SELECT course_learning_profile_id FROM test_attempts")[0][0] == profile_id


def test_multiple_practice_learners_do_not_inherit_ambiguous_global_history(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "multiple-learners-legacy.db"
    _upgrade_to_0013(db_path, monkeypatch)
    course_id = _seed_legacy_course(
        db_path, ["alice", "bob"], include_global_history=True
    )

    _upgrade_to_0014()

    profiles = _rows(
        db_path,
        "SELECT id, learner_id, course_id FROM course_learning_profiles",
    )
    assert {row["learner_id"] for row in profiles} == {
        _canonical_learner_id("alice"),
        _canonical_learner_id("bob"),
        LEGACY_LOCAL_LEARNER_ID,
    }
    legacy_profile_id = next(
        row["id"]
        for row in profiles
        if row["learner_id"] == LEGACY_LOCAL_LEARNER_ID
        and row["course_id"] == course_id
    )
    assert _rows(db_path, "SELECT course_learning_profile_id FROM review_states")[0][0] == legacy_profile_id
    assert _rows(db_path, "SELECT course_learning_profile_id FROM review_logs")[0][0] == legacy_profile_id
    assert _rows(db_path, "SELECT course_learning_profile_id FROM test_attempts")[0][0] == legacy_profile_id
