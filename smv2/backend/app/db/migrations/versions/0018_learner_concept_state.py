"""learner state projections and immutable shadow predictions

Revision ID: 0018_learner_concept_state
Revises: 0017_learner_evidence_ledger
Create Date: 2026-08-02

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_learner_concept_state"
down_revision: Union[str, None] = "0017_learner_evidence_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learner_concept_states",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("course_learning_profile_id", sa.String(), nullable=False),
        sa.Column("curriculum_version_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("learning_claim_id", sa.String(), nullable=True),
        sa.Column("state_scope", sa.String(), nullable=False),
        sa.Column("state_key", sa.String(), nullable=False),
        sa.Column("readiness_estimate", sa.Float(), nullable=True),
        sa.Column("quiz_estimate", sa.Float(), nullable=True),
        sa.Column("review_estimate", sa.Float(), nullable=True),
        sa.Column("lower_bound", sa.Float(), nullable=True),
        sa.Column("upper_bound", sa.Float(), nullable=True),
        sa.Column("uncertainty", sa.Float(), nullable=True),
        sa.Column("effective_evidence_count", sa.Float(), nullable=False),
        sa.Column("distinct_item_count", sa.Integer(), nullable=False),
        sa.Column("distinct_session_count", sa.Integer(), nullable=False),
        sa.Column("trend", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("forgetting_risk", sa.Float(), nullable=False),
        sa.Column("last_evidence_at", sa.DateTime(), nullable=True),
        sa.Column("calculated_through", sa.DateTime(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "state_scope IN ('claim', 'concept')",
            name="ck_learner_concept_states_scope",
        ),
        sa.CheckConstraint(
            "status IN ('insufficient_evidence', 'likely_struggling', 'building', "
            "'watch', 'retained')",
            name="ck_learner_concept_states_status",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["course_learning_profile_id"],
            ["course_learning_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["learning_claim_id"], ["learning_claims.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_learning_profile_id",
            "curriculum_version_id",
            "state_key",
            "model_version",
            name="uq_learner_concept_states_projection",
        ),
    )
    for column in (
        "course_id",
        "course_learning_profile_id",
        "curriculum_version_id",
        "concept_id",
        "learning_claim_id",
    ):
        op.create_index(
            f"ix_learner_concept_states_{column}", "learner_concept_states", [column]
        )

    op.create_table(
        "shadow_learner_predictions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("course_learning_profile_id", sa.String(), nullable=False),
        sa.Column("curriculum_version_id", sa.String(), nullable=False),
        sa.Column("learning_claim_id", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("predicted_probability", sa.Float(), nullable=True),
        sa.Column("evidence_snapshot_hash", sa.String(), nullable=False),
        sa.Column("training_cutoff", sa.DateTime(), nullable=False),
        sa.Column("feature_schema_version", sa.String(), nullable=False),
        sa.Column("prediction_horizon", sa.String(), nullable=False),
        sa.Column("target_definition", sa.Text(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('predicted', 'insufficient_data', 'disabled')",
            name="ck_shadow_learner_predictions_status",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["course_learning_profile_id"],
            ["course_learning_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["learning_claim_id"], ["learning_claims.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_learning_profile_id",
            "learning_claim_id",
            "model_name",
            "model_version",
            "evidence_snapshot_hash",
            name="uq_shadow_learner_predictions_snapshot",
        ),
    )
    for column in (
        "course_id",
        "course_learning_profile_id",
        "curriculum_version_id",
        "learning_claim_id",
    ):
        op.create_index(
            f"ix_shadow_learner_predictions_{column}",
            "shadow_learner_predictions",
            [column],
        )
    op.execute(
        """
        CREATE TRIGGER shadow_learner_predictions_no_update
        BEFORE UPDATE ON shadow_learner_predictions
        BEGIN
            SELECT RAISE(ABORT, 'shadow learner predictions are immutable');
        END;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS shadow_learner_predictions_no_update")
    for column in (
        "learning_claim_id",
        "curriculum_version_id",
        "course_learning_profile_id",
        "course_id",
    ):
        op.drop_index(
            f"ix_shadow_learner_predictions_{column}",
            table_name="shadow_learner_predictions",
        )
    op.drop_table("shadow_learner_predictions")
    for column in (
        "learning_claim_id",
        "concept_id",
        "curriculum_version_id",
        "course_learning_profile_id",
        "course_id",
    ):
        op.drop_index(
            f"ix_learner_concept_states_{column}", table_name="learner_concept_states"
        )
    op.drop_table("learner_concept_states")
