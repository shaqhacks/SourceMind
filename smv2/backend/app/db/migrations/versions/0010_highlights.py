"""highlights table

Revision ID: 0010_highlights
Revises: 0009_inline_practice_assessments
Create Date: 2026-07-17

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_highlights"
down_revision: Union[str, None] = "0009_inline_practice_assessments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "highlights",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("exact", sa.Text(), nullable=False),
        sa.Column("prefix", sa.String(length=64), nullable=False),
        sa.Column("suffix", sa.String(length=64), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("note_md", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_highlights_course_id", "highlights", ["course_id"])
    op.create_index("ix_highlights_section_id", "highlights", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_highlights_section_id", table_name="highlights")
    op.drop_index("ix_highlights_course_id", table_name="highlights")
    op.drop_table("highlights")
