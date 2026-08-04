"""diagnostic validation and delayed retention studies

Revision ID: 0019_diagnostic_validation
Revises: 0018_learner_concept_state
Create Date: 2026-08-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_diagnostic_validation"
down_revision: Union[str, None] = "0018_learner_concept_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_judgments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("course_learning_profile_id", sa.String(), nullable=False),
        sa.Column("curriculum_version_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("reviewer_key", sa.String(), nullable=False),
        sa.Column("judgment", sa.String(), nullable=False),
        sa.Column("disagreement_reason", sa.String(), nullable=True),
        sa.Column("notes_md", sa.Text(), nullable=True),
        sa.Column("model_state", sa.String(), nullable=False),
        sa.Column("readiness_estimate", sa.Float(), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("state_calculated_at", sa.DateTime(), nullable=False),
        sa.Column("agreement", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("judgment IN ('insufficient', 'not_struggling', 'uncertain', 'likely_struggling')", name="ck_diagnostic_judgments_judgment"),
        sa.CheckConstraint("disagreement_reason IS NULL OR disagreement_reason IN ('model_estimate', 'item_mapping', 'concept_granularity', 'insufficient_student_evidence', 'instructor_disagreement')", name="ck_diagnostic_judgments_reason"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_learning_profile_id"], ["course_learning_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_learning_profile_id", "curriculum_version_id", "concept_id", "reviewer_key", name="uq_diagnostic_judgments_blind_review"),
    )
    for column in ("course_id", "course_learning_profile_id", "curriculum_version_id", "concept_id"):
        op.create_index(f"ix_diagnostic_judgments_{column}", "diagnostic_judgments", [column])

    op.create_table(
        "retention_studies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("assignment_seed", sa.String(), nullable=False),
        sa.Column("protocol_version", sa.String(), nullable=False),
        sa.Column("delay_start_days", sa.Integer(), nullable=False),
        sa.Column("delay_end_days", sa.Integer(), nullable=False),
        sa.Column("minimum_per_group", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'active', 'closed')", name="ck_retention_studies_status"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_retention_studies_course_id", "retention_studies", ["course_id"])

    op.create_table(
        "retention_assignments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("course_learning_profile_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("study_group", sa.String(), nullable=False),
        sa.Column("workload_target", sa.Integer(), nullable=False),
        sa.Column("assignment_key", sa.String(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("study_group IN ('adaptive_targeted', 'baseline_review')", name="ck_retention_assignments_group"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["study_id"], ["retention_studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_learning_profile_id"], ["course_learning_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_key", name="uq_retention_assignments_key"),
        sa.UniqueConstraint("study_id", "course_learning_profile_id", "concept_id", name="uq_retention_assignments_pair"),
    )
    for column in ("course_id", "study_id", "course_learning_profile_id", "concept_id"):
        op.create_index(f"ix_retention_assignments_{column}", "retention_assignments", [column])

    op.create_table(
        "retention_probes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("assignment_id", sa.String(), nullable=False),
        sa.Column("evidence_item_id", sa.String(), nullable=False),
        sa.Column("learning_claim_id", sa.String(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("outcome_event_id", sa.String(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('scheduled', 'completed', 'missed', 'cancelled')", name="ck_retention_probes_status"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["retention_assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_item_id"], ["evidence_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["learning_claim_id"], ["learning_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outcome_event_id"], ["learner_evidence_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "evidence_item_id", name="uq_retention_probes_item"),
    )
    for column in ("course_id", "assignment_id", "evidence_item_id", "learning_claim_id"):
        op.create_index(f"ix_retention_probes_{column}", "retention_probes", [column])

    op.execute("CREATE TRIGGER retention_assignments_no_update BEFORE UPDATE ON retention_assignments BEGIN SELECT RAISE(ABORT, 'retention assignments are immutable'); END;")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS retention_assignments_no_update")
    for table, columns in (
        ("retention_probes", ("learning_claim_id", "evidence_item_id", "assignment_id", "course_id")),
        ("retention_assignments", ("concept_id", "course_learning_profile_id", "study_id", "course_id")),
    ):
        for column in columns:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_table(table)
    op.drop_index("ix_retention_studies_course_id", table_name="retention_studies")
    op.drop_table("retention_studies")
    for column in ("concept_id", "curriculum_version_id", "course_learning_profile_id", "course_id"):
        op.drop_index(f"ix_diagnostic_judgments_{column}", table_name="diagnostic_judgments")
    op.drop_table("diagnostic_judgments")
