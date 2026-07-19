"""highlight surface discriminator

Revision ID: 0011_highlight_surface
Revises: 0010_highlights
Create Date: 2026-07-18

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_highlight_surface"
down_revision: Union[str, None] = "0010_highlights"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "highlights",
        sa.Column("surface", sa.String(), nullable=False, server_default="source"),
    )


def downgrade() -> None:
    op.drop_column("highlights", "surface")
