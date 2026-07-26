"""notes table

Revision ID: 0012_notes
Revises: 0011_highlight_surface
Create Date: 2026-07-21

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_notes"
down_revision: Union[str, None] = "0011_highlight_surface"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("surface", sa.String(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("anchor_y", sa.Float(), nullable=False),
        sa.Column("note_md", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notes_course_id", "notes", ["course_id"])
    op.create_index("ix_notes_section_id", "notes", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_notes_section_id", table_name="notes")
    op.drop_index("ix_notes_course_id", table_name="notes")
    op.drop_table("notes")
