"""append-only learner evidence ledger

Revision ID: 0017_learner_evidence_ledger
Revises: 0016_evidence_items
Create Date: 2026-08-02

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_learner_evidence_ledger"
down_revision: Union[str, None] = "0016_evidence_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learner_evidence_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("course_learning_profile_id", sa.String(), nullable=False),
        sa.Column("evidence_item_id", sa.String(), nullable=False),
        sa.Column("evidence_mapping_id", sa.String(), nullable=True),
        sa.Column("learning_claim_id", sa.String(), nullable=True),
        sa.Column("curriculum_version_id", sa.String(), nullable=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("normalized_outcome", sa.Float(), nullable=False),
        sa.Column("raw_result", sa.JSON(), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("attempt_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("source_event_key", sa.String(), nullable=False),
        sa.Column("spacing_seconds", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "channel IN ('practice', 'quiz', 'review')",
            name="ck_learner_evidence_events_channel",
        ),
        sa.CheckConstraint(
            "normalized_outcome >= 0 AND normalized_outcome <= 1",
            name="ck_learner_evidence_events_outcome",
        ),
        sa.CheckConstraint(
            "spacing_seconds IS NULL OR spacing_seconds >= 0",
            name="ck_learner_evidence_events_spacing",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["course_learning_profile_id"],
            ["course_learning_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"], ["evidence_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_mapping_id"],
            ["evidence_item_concept_links.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["learning_claim_id"], ["learning_claims.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"], ["curriculum_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_key", name="uq_learner_evidence_events_source"),
    )
    for column in (
        "course_id",
        "course_learning_profile_id",
        "evidence_item_id",
        "learning_claim_id",
    ):
        op.create_index(
            f"ix_learner_evidence_events_{column}",
            "learner_evidence_events",
            [column],
        )
    op.execute(
        """
        CREATE TRIGGER learner_evidence_events_no_update
        BEFORE UPDATE ON learner_evidence_events
        BEGIN
            SELECT RAISE(ABORT, 'learner evidence events are append-only');
        END;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS learner_evidence_events_no_update")
    for column in (
        "learning_claim_id",
        "evidence_item_id",
        "course_learning_profile_id",
        "course_id",
    ):
        op.drop_index(
            f"ix_learner_evidence_events_{column}",
            table_name="learner_evidence_events",
        )
    op.drop_table("learner_evidence_events")
