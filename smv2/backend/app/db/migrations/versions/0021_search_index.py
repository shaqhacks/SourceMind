"""local search index

Revision ID: 0021_search_index
Revises: 0020_course_is_sample
Create Date: 2026-08-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_search_index"
down_revision: Union[str, None] = "0020_course_is_sample"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "search_documents",
        sa.Column("doc_key", sa.Text(), primary_key=True),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("section_id", sa.Text(), nullable=True),
        sa.Column("asset_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_heading", sa.Text(), nullable=True),
        sa.Column("source_chapter", sa.Text(), nullable=True),
        sa.Column("source_slide", sa.Text(), nullable=True),
    )
    op.create_index("ix_search_documents_course", "search_documents", ["course_id"])
    op.create_index(
        "ix_search_documents_type_course",
        "search_documents",
        ["course_id", "doc_type"],
    )

    bind = op.get_bind()
    from app.services import search_index

    if search_index.fts5_available(bind):
        bind.exec_driver_sql(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts
            USING fts5(title, body, content='search_documents', content_rowid='rowid')
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP TABLE IF EXISTS search_documents_fts")
    op.drop_index("ix_search_documents_type_course", table_name="search_documents")
    op.drop_index("ix_search_documents_course", table_name="search_documents")
    op.drop_table("search_documents")
