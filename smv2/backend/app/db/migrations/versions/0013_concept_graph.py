"""concept graph: edges + section links

Revision ID: 0013_concept_graph
Revises: 0012_notes
Create Date: 2026-07-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_concept_graph"
down_revision: Union[str, None] = "0012_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "concept_edges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("from_concept_id", sa.String(), nullable=False),
        sa.Column("to_concept_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_id", "from_concept_id", "to_concept_id", name="uq_concept_edges"
        ),
    )
    op.create_index("ix_concept_edges_course_id", "concept_edges", ["course_id"])
    op.create_index("ix_concept_edges_from_concept_id", "concept_edges", ["from_concept_id"])
    op.create_index("ix_concept_edges_to_concept_id", "concept_edges", ["to_concept_id"])

    op.create_table(
        "concept_section_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("relevance_md", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concept_id", "section_id", name="uq_concept_section_links"),
    )
    op.create_index("ix_concept_section_links_course_id", "concept_section_links", ["course_id"])
    op.create_index(
        "ix_concept_section_links_concept_id", "concept_section_links", ["concept_id"]
    )
    op.create_index(
        "ix_concept_section_links_section_id", "concept_section_links", ["section_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_concept_section_links_section_id", table_name="concept_section_links")
    op.drop_index("ix_concept_section_links_concept_id", table_name="concept_section_links")
    op.drop_index("ix_concept_section_links_course_id", table_name="concept_section_links")
    op.drop_table("concept_section_links")

    op.drop_index("ix_concept_edges_to_concept_id", table_name="concept_edges")
    op.drop_index("ix_concept_edges_from_concept_id", table_name="concept_edges")
    op.drop_index("ix_concept_edges_course_id", table_name="concept_edges")
    op.drop_table("concept_edges")
