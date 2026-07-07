"""Deck/attempt split (ADR-022): `tests` holds the generated questions
once; `test_attempts` holds only this attempt's own answers/results/score,
linked by test_id. Retaking a test creates a new TestAttempt against the
SAME Test row, zero further LLM calls.

Every existing test_attempts row gets a backfilled Test, built from that
same row's own payload/chapter_label/section_id/prompt_version (model is
NULL for backfilled rows -- it was never tracked pre-split, no historical
value to recover).

Revision ID: 0007_test_deck_attempt_split
Revises: 0006_asset_html_status
Create Date: 2026-07-06

"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_test_deck_attempt_split"
down_revision: Union[str, None] = "0006_asset_html_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chapter_label", sa.String(), nullable=True),
        sa.Column(
            "section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tests_course_id", "tests", ["course_id"])

    # --- Data backfill: one Test per existing test_attempts row ---------
    # Lightweight Core table declarations bound to THIS migration's own
    # connection, not the live ORM models — the standard Alembic pattern,
    # so a future model change can never silently break this historical
    # migration.
    bind = op.get_bind()
    metadata = sa.MetaData()
    legacy_test_attempts = sa.Table(
        "test_attempts",
        metadata,
        sa.Column("id", sa.String()),
        sa.Column("course_id", sa.String()),
        sa.Column("section_id", sa.String()),
        sa.Column("payload", sa.JSON()),
        sa.Column("prompt_version", sa.String()),
        sa.Column("chapter_label", sa.String()),
        sa.Column("created_at", sa.DateTime()),
    )
    tests_table = sa.Table(
        "tests",
        metadata,
        sa.Column("id", sa.String()),
        sa.Column("course_id", sa.String()),
        sa.Column("chapter_label", sa.String()),
        sa.Column("section_id", sa.String()),
        sa.Column("questions", sa.JSON()),
        sa.Column("prompt_version", sa.String()),
        sa.Column("model", sa.String()),
        sa.Column("created_at", sa.DateTime()),
    )

    legacy_rows = bind.execute(sa.select(legacy_test_attempts)).fetchall()
    test_id_by_attempt_id: dict[str, str] = {}
    for row in legacy_rows:
        new_test_id = str(uuid.uuid4())
        test_id_by_attempt_id[row.id] = new_test_id
        questions = (row.payload or {}).get("questions", [])
        bind.execute(
            tests_table.insert().values(
                id=new_test_id,
                course_id=row.course_id,
                chapter_label=row.chapter_label,
                section_id=row.section_id,
                questions=questions,
                prompt_version=row.prompt_version,
                model=None,
                created_at=row.created_at,
            )
        )

    # test_id added NULLABLE first -- SQLite/Alembic can't add a NOT NULL
    # column with no default to a table that already has rows (the batch
    # rebuild's data copy would have nothing to put in it). Backfilled
    # below, then tightened to NOT NULL (+ the FK constraint) in a SECOND
    # batch_alter_table pass once every row actually has a value. Also add
    # answers/results here -- both genuinely nullable (NULL until an
    # attempt is submitted), no backfill needed since neither was ever
    # persisted before this migration (submit_test computed and returned
    # them but never wrote them to the DB).
    with op.batch_alter_table("test_attempts") as batch_op:
        batch_op.add_column(sa.Column("test_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("answers", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("results", sa.JSON(), nullable=True))

    test_id_column = sa.Table(
        "test_attempts", sa.MetaData(), sa.Column("id", sa.String()), sa.Column("test_id", sa.String())
    )
    for row in legacy_rows:
        bind.execute(
            test_id_column.update()
            .where(test_id_column.c.id == row.id)
            .values(test_id=test_id_by_attempt_id[row.id])
        )

    with op.batch_alter_table("test_attempts") as batch_op:
        batch_op.alter_column("test_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_test_attempts_test_id_tests", "tests", ["test_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.drop_column("payload")
        batch_op.drop_column("chapter_label")
        batch_op.drop_column("section_id")
        # prompt_version moved to Test too (the deck's own provenance, not
        # per-attempt) -- Test.prompt_version was already backfilled above.
        batch_op.drop_column("prompt_version")


def downgrade() -> None:
    with op.batch_alter_table("test_attempts") as batch_op:
        batch_op.add_column(sa.Column("chapter_label", sa.String(), nullable=True))
        # Inline sa.ForeignKey(...) on a column added mid-batch has no name
        # of its own -- batch mode requires every constraint to be named
        # (raises "Constraint must have a name" otherwise), so the FK is
        # added as its own separately-named create_foreign_key call below
        # instead, same pattern as migration 0005.
        batch_op.add_column(sa.Column("section_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("payload", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("prompt_version", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_test_attempts_section_id_sections", "sections", ["section_id"], ["id"], ondelete="SET NULL"
        )

    bind = op.get_bind()
    metadata = sa.MetaData()
    tests_table = sa.Table(
        "tests",
        metadata,
        sa.Column("id", sa.String()),
        sa.Column("chapter_label", sa.String()),
        sa.Column("section_id", sa.String()),
        sa.Column("questions", sa.JSON()),
        sa.Column("prompt_version", sa.String()),
    )
    attempts_table = sa.Table(
        "test_attempts",
        metadata,
        sa.Column("id", sa.String()),
        sa.Column("test_id", sa.String()),
        sa.Column("chapter_label", sa.String()),
        sa.Column("section_id", sa.String()),
        sa.Column("payload", sa.JSON()),
        sa.Column("prompt_version", sa.String()),
    )
    for attempt_id, test_id in bind.execute(sa.select(attempts_table.c.id, attempts_table.c.test_id)):
        test_row = bind.execute(sa.select(tests_table).where(tests_table.c.id == test_id)).first()
        if test_row is None:
            continue
        bind.execute(
            attempts_table.update()
            .where(attempts_table.c.id == attempt_id)
            .values(
                chapter_label=test_row.chapter_label,
                section_id=test_row.section_id,
                payload={"questions": test_row.questions},
                prompt_version=test_row.prompt_version,
            )
        )

    with op.batch_alter_table("test_attempts") as batch_op:
        batch_op.alter_column("payload", nullable=False)
        batch_op.drop_column("results")
        batch_op.drop_column("answers")
        batch_op.drop_column("test_id")

    op.drop_index("ix_tests_course_id", table_name="tests")
    op.drop_table("tests")
