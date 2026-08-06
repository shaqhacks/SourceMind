"""source locator and detected asset format metadata

Revision ID: 0022_source_locators
Revises: 0021_search_index
Create Date: 2026-08-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_source_locators"
down_revision: str | None = "0021_search_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("source_format", sa.String(), nullable=False, server_default="pdf"),
    )
    op.add_column(
        "assets",
        sa.Column("media_type", sa.String(), nullable=False, server_default="application/pdf"),
    )
    op.add_column("sections", sa.Column("source_format", sa.String(), nullable=True))
    op.add_column("sections", sa.Column("source_locator", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sections") as batch_op:
        batch_op.drop_column("source_locator")
        batch_op.drop_column("source_format")
    with op.batch_alter_table("assets") as batch_op:
        batch_op.drop_column("media_type")
        batch_op.drop_column("source_format")
