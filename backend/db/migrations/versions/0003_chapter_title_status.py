"""Add chapters.title_status for lazy placeholder-title refinement (ADR-010).

Zero-LLM ingest can now leave a chapter with a deterministic placeholder title
("Pages A-B") when no bookmarks are available. This column tracks whether that
title still needs a one-shot lazy LLM refinement (see
``pipeline.service.maybe_refine_title``/``run_title_refinement_job``):
None/"toc" = authoritative title, no refinement needed; "placeholder" = needs
refinement; "refining"/"refined"/"failed" = in-flight/terminal states of that
refinement (mirrors the existing ``chapters.lesson_status`` pattern).

Existing rows get NULL (treated as "no refinement needed" — safe default for
data ingested before this feature).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chapters") as batch_op:
        batch_op.add_column(sa.Column("title_status", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chapters") as batch_op:
        batch_op.drop_column("title_status")
