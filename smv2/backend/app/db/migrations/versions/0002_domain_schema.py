"""domain schema: courses, assets, sections, chunks, cards, review, progress,
chat, test_attempts, llm_calls; jobs.progress

Revision ID: 0002_domain_schema
Revises: 0001_jobs
Create Date: 2026-07-05

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_domain_schema"
down_revision: Union[str, None] = "0001_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("progress", sa.JSON(), nullable=True))

    op.create_table(
        "courses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("stored_path", sa.String(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_course_id", "assets", ["course_id"])

    op.create_table(
        "sections",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("lesson_md", sa.Text(), nullable=True),
        sa.Column("lesson_status", sa.String(), nullable=False),
        sa.Column("lesson_model", sa.String(), nullable=True),
        sa.Column("lesson_prompt_version", sa.String(), nullable=True),
        sa.Column("extractor_version", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sections_course_id", "sections", ["course_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunks_course_id", "chunks", ["course_id"])
    op.create_index("ix_chunks_section_id", "chunks", ["section_id"])

    op.create_table(
        "cards",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("front_md", sa.Text(), nullable=False),
        sa.Column("back_md", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cards_course_id", "cards", ["course_id"])
    op.create_index("ix_cards_section_id", "cards", ["section_id"])

    op.create_table(
        "review_states",
        sa.Column(
            "card_id", sa.String(), sa.ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("interval_days", sa.Float(), nullable=False),
        sa.Column("ease", sa.Float(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("last_grade", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("card_id"),
    )
    op.create_index("ix_review_states_course_id", "review_states", ["course_id"])

    op.create_table(
        "review_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "card_id", sa.String(), sa.ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("graded_at", sa.DateTime(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_logs_card_id", "review_logs", ["card_id"])
    op.create_index("ix_review_logs_course_id", "review_logs", ["course_id"])

    op.create_table(
        "progress_states",
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("scroll_pos", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("course_id"),
    )

    op.create_table(
        "chat_turns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_turns_course_id", "chat_turns", ["course_id"])

    op.create_table(
        "test_attempts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_attempts_course_id", "test_attempts", ["course_id"])

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_estimate", sa.Float(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_calls_course_id", "llm_calls", ["course_id"])

    op.execute(
        """
        CREATE TRIGGER sections_body_md_immutable
        BEFORE UPDATE OF body_md ON sections
        WHEN NEW.body_md IS NOT OLD.body_md
        BEGIN
            SELECT RAISE(ABORT, 'body_md is immutable');
        END;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS sections_body_md_immutable")
    op.drop_table("llm_calls")
    op.drop_table("test_attempts")
    op.drop_table("chat_turns")
    op.drop_table("progress_states")
    op.drop_table("review_logs")
    op.drop_table("review_states")
    op.drop_table("cards")
    op.drop_table("chunks")
    op.drop_table("sections")
    op.drop_table("assets")
    op.drop_table("courses")
    op.drop_column("jobs", "progress")
