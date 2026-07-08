"""inline practice assessment tables

Revision ID: 0009_inline_practice_assessments
Revises: 0008_card_origin
Create Date: 2026-07-07

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_inline_practice_assessments"
down_revision: Union[str, None] = "0008_card_origin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "concepts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("chapter_label", sa.String(), nullable=True),
        sa.Column(
            "section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "slug", name="uq_concepts_course_slug"),
    )
    op.create_index("ix_concepts_course_id", "concepts", ["course_id"])

    op.create_table(
        "practice_questions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chapter_label", sa.String(), nullable=True),
        sa.Column(
            "section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "concept_id", sa.String(), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "source_asset_id", sa.String(), sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("source_page_start", sa.Integer(), nullable=True),
        sa.Column("source_page_end", sa.Integer(), nullable=True),
        sa.Column("problem_number", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column(
            "answer_section_id",
            sa.String(),
            sa.ForeignKey("sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("answer_source_ref", sa.String(), nullable=True),
        sa.Column("stem_md", sa.Text(), nullable=False),
        sa.Column("choices", sa.JSON(), nullable=False),
        sa.Column("correct_index", sa.Integer(), nullable=False),
        sa.Column("explanation_md", sa.Text(), nullable=False),
        sa.Column("source_fingerprint", sa.String(), nullable=False),
        sa.Column("extraction_version", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_id",
            "section_id",
            "source_fingerprint",
            name="uq_practice_questions_source",
        ),
    )
    op.create_index("ix_practice_questions_concept_id", "practice_questions", ["concept_id"])
    op.create_index("ix_practice_questions_course_id", "practice_questions", ["course_id"])
    op.create_index("ix_practice_questions_section_id", "practice_questions", ["section_id"])

    op.create_table(
        "practice_extraction_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("input_fingerprint", sa.String(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_id",
            "section_id",
            "input_fingerprint",
            name="uq_practice_runs_input",
        ),
    )
    op.create_index("ix_practice_extraction_runs_course_id", "practice_extraction_runs", ["course_id"])
    op.create_index("ix_practice_extraction_runs_section_id", "practice_extraction_runs", ["section_id"])

    op.create_table(
        "practice_answers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "question_id",
            sa.String(),
            sa.ForeignKey("practice_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("learner_key", sa.String(), nullable=False),
        sa.Column("selected_index", sa.Integer(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "learner_key",
            "question_id",
            name="uq_practice_answers_learner_question",
        ),
    )
    op.create_index("ix_practice_answers_course_id", "practice_answers", ["course_id"])
    op.create_index("ix_practice_answers_learner_key", "practice_answers", ["learner_key"])
    op.create_index("ix_practice_answers_question_id", "practice_answers", ["question_id"])

    op.create_table(
        "concept_masteries",
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "concept_id", sa.String(), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("learner_key", sa.String(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("wrong_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("course_id", "concept_id", "learner_key"),
    )

    op.create_table(
        "concept_mastery_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "concept_id", sa.String(), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "question_id",
            sa.String(),
            sa.ForeignKey("practice_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "practice_answer_id",
            sa.String(),
            sa.ForeignKey("practice_answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("learner_key", sa.String(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_concept_mastery_events_concept_id", "concept_mastery_events", ["concept_id"])
    op.create_index("ix_concept_mastery_events_course_id", "concept_mastery_events", ["course_id"])
    op.create_index("ix_concept_mastery_events_learner_key", "concept_mastery_events", ["learner_key"])
    op.create_index(
        "ix_concept_mastery_events_practice_answer_id",
        "concept_mastery_events",
        ["practice_answer_id"],
    )
    op.create_index("ix_concept_mastery_events_question_id", "concept_mastery_events", ["question_id"])


def downgrade() -> None:
    op.drop_table("concept_mastery_events")
    op.drop_table("concept_masteries")
    op.drop_table("practice_answers")
    op.drop_table("practice_extraction_runs")
    op.drop_table("practice_questions")
    op.drop_table("concepts")
