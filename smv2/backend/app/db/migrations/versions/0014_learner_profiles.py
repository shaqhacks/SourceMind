"""learner identity and course-scoped learning profiles

Revision ID: 0014_learner_profiles
Revises: 0013_concept_graph
Create Date: 2026-08-02

"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_learner_profiles"
down_revision: Union[str, None] = "0013_concept_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_LOCAL_LEARNER_ID = "00000000-0000-0000-0000-000000000001"


def _canonical_learner_id(learner_key: str) -> str:
    try:
        return str(uuid.UUID(learner_key))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sourcemind:learner:{learner_key}"))


def _course_profile_id(learner_id: str, course_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sourcemind:course-profile:{learner_id}:{course_id}"))


def upgrade() -> None:
    op.create_table(
        "learner_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "course_learning_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("learner_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["learner_id"], ["learner_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "learner_id", "course_id", name="uq_course_learning_profiles_learner_course"
        ),
    )
    op.create_index(
        "ix_course_learning_profiles_course_id", "course_learning_profiles", ["course_id"]
    )
    op.create_index(
        "ix_course_learning_profiles_learner_id", "course_learning_profiles", ["learner_id"]
    )

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    practice_rows = bind.execute(
        sa.text("SELECT DISTINCT course_id, learner_key FROM practice_answers")
    ).mappings()
    learner_ids_by_course: dict[str, set[str]] = {}
    learner_ids: set[str] = set()
    course_profiles: set[tuple[str, str]] = set()
    for row in practice_rows:
        learner_id = _canonical_learner_id(row["learner_key"])
        course_id = row["course_id"]
        learner_ids.add(learner_id)
        learner_ids_by_course.setdefault(course_id, set()).add(learner_id)
        course_profiles.add((learner_id, course_id))

    globally_scoped_course_ids = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT course_id FROM review_states "
                "UNION SELECT course_id FROM review_logs "
                "UNION SELECT course_id FROM test_attempts"
            )
        )
    }
    default_profile_by_course: dict[str, str] = {}
    for course_id in globally_scoped_course_ids:
        candidates = learner_ids_by_course.get(course_id, set())
        learner_id = next(iter(candidates)) if len(candidates) == 1 else _LEGACY_LOCAL_LEARNER_ID
        learner_ids.add(learner_id)
        course_profiles.add((learner_id, course_id))
        default_profile_by_course[course_id] = _course_profile_id(learner_id, course_id)

    for learner_id in sorted(learner_ids):
        bind.execute(
            sa.text(
                "INSERT INTO learner_profiles (id, created_at, updated_at) "
                "VALUES (:id, :created_at, :updated_at)"
            ),
            {"id": learner_id, "created_at": now, "updated_at": now},
        )
    for learner_id, course_id in sorted(course_profiles):
        bind.execute(
            sa.text(
                "INSERT INTO course_learning_profiles "
                "(id, learner_id, course_id, created_at, updated_at) "
                "VALUES (:id, :learner_id, :course_id, :created_at, :updated_at)"
            ),
            {
                "id": _course_profile_id(learner_id, course_id),
                "learner_id": learner_id,
                "course_id": course_id,
                "created_at": now,
                "updated_at": now,
            },
        )

    op.rename_table("review_states", "review_states_legacy_0014")
    op.drop_index("ix_review_states_course_id", table_name="review_states_legacy_0014")
    op.create_table(
        "review_states",
        sa.Column("course_learning_profile_id", sa.String(), nullable=False),
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("interval_days", sa.Float(), nullable=False),
        sa.Column("ease", sa.Float(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("last_grade", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["course_learning_profile_id"],
            ["course_learning_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("course_learning_profile_id", "card_id"),
        sa.UniqueConstraint(
            "course_learning_profile_id", "card_id", name="uq_review_states_profile_card"
        ),
    )
    op.create_index("ix_review_states_course_id", "review_states", ["course_id"])
    legacy_states = bind.execute(sa.text("SELECT * FROM review_states_legacy_0014")).mappings()
    for row in legacy_states:
        bind.execute(
            sa.text(
                "INSERT INTO review_states "
                "(course_learning_profile_id, card_id, course_id, due_at, interval_days, "
                "ease, reps, lapses, last_grade, updated_at) "
                "VALUES (:course_learning_profile_id, :card_id, :course_id, :due_at, "
                ":interval_days, :ease, :reps, :lapses, :last_grade, :updated_at)"
            ),
            {**dict(row), "course_learning_profile_id": default_profile_by_course[row["course_id"]]},
        )
    op.drop_table("review_states_legacy_0014")

    with op.batch_alter_table("review_logs") as batch_op:
        batch_op.add_column(sa.Column("course_learning_profile_id", sa.String(), nullable=True))
    review_logs = sa.table(
        "review_logs",
        sa.column("course_id", sa.String()),
        sa.column("course_learning_profile_id", sa.String()),
    )
    for course_id, profile_id in default_profile_by_course.items():
        bind.execute(
            review_logs.update()
            .where(review_logs.c.course_id == course_id)
            .values(course_learning_profile_id=profile_id)
        )
    with op.batch_alter_table("review_logs") as batch_op:
        batch_op.alter_column("course_learning_profile_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_review_logs_course_learning_profile_id",
            "course_learning_profiles",
            ["course_learning_profile_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "ix_review_logs_course_learning_profile_id", ["course_learning_profile_id"]
        )

    with op.batch_alter_table("test_attempts") as batch_op:
        batch_op.add_column(sa.Column("course_learning_profile_id", sa.String(), nullable=True))
    test_attempts = sa.table(
        "test_attempts",
        sa.column("course_id", sa.String()),
        sa.column("course_learning_profile_id", sa.String()),
    )
    for course_id, profile_id in default_profile_by_course.items():
        bind.execute(
            test_attempts.update()
            .where(test_attempts.c.course_id == course_id)
            .values(course_learning_profile_id=profile_id)
        )
    with op.batch_alter_table("test_attempts") as batch_op:
        batch_op.alter_column("course_learning_profile_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_test_attempts_course_learning_profile_id",
            "course_learning_profiles",
            ["course_learning_profile_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "ix_test_attempts_course_learning_profile_id", ["course_learning_profile_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("test_attempts") as batch_op:
        batch_op.drop_index("ix_test_attempts_course_learning_profile_id")
        batch_op.drop_constraint(
            "fk_test_attempts_course_learning_profile_id", type_="foreignkey"
        )
        batch_op.drop_column("course_learning_profile_id")

    with op.batch_alter_table("review_logs") as batch_op:
        batch_op.drop_index("ix_review_logs_course_learning_profile_id")
        batch_op.drop_constraint(
            "fk_review_logs_course_learning_profile_id", type_="foreignkey"
        )
        batch_op.drop_column("course_learning_profile_id")

    bind = op.get_bind()
    op.rename_table("review_states", "review_states_scoped_0014")
    op.drop_index("ix_review_states_course_id", table_name="review_states_scoped_0014")
    op.create_table(
        "review_states",
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("interval_days", sa.Float(), nullable=False),
        sa.Column("ease", sa.Float(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("last_grade", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("card_id"),
    )
    op.create_index("ix_review_states_course_id", "review_states", ["course_id"])
    scoped_rows = bind.execute(
        sa.text("SELECT * FROM review_states_scoped_0014 ORDER BY updated_at DESC")
    ).mappings()
    copied_card_ids: set[str] = set()
    for row in scoped_rows:
        if row["card_id"] in copied_card_ids:
            continue
        copied_card_ids.add(row["card_id"])
        bind.execute(
            sa.text(
                "INSERT INTO review_states "
                "(card_id, course_id, due_at, interval_days, ease, reps, lapses, "
                "last_grade, updated_at) VALUES (:card_id, :course_id, :due_at, "
                ":interval_days, :ease, :reps, :lapses, :last_grade, :updated_at)"
            ),
            {key: row[key] for key in (
                "card_id", "course_id", "due_at", "interval_days", "ease",
                "reps", "lapses", "last_grade", "updated_at"
            )},
        )
    op.drop_table("review_states_scoped_0014")

    op.drop_index(
        "ix_course_learning_profiles_learner_id", table_name="course_learning_profiles"
    )
    op.drop_index(
        "ix_course_learning_profiles_course_id", table_name="course_learning_profiles"
    )
    op.drop_table("course_learning_profiles")
    op.drop_table("learner_profiles")
