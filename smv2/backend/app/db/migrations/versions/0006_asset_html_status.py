"""assets.html_status: pdf2htmlEX conversion state per asset (ADR-020).

Revision ID: 0006_asset_html_status
Revises: 0005_section_asset_id
Create Date: 2026-07-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_asset_html_status"
down_revision: Union[str, None] = "0005_section_asset_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain add_column is safe here (no FK, so no batch_alter_table needed —
    # see ADR-019 for why that would matter if this DID add a constraint).
    # assets has no triggers today (only sections_body_md_immutable does,
    # scoped to sections) — verified against every prior migration before
    # relying on plain add_column being safe.
    op.add_column(
        "assets",
        sa.Column("html_status", sa.String(), nullable=False, server_default="none"),
    )


def downgrade() -> None:
    op.drop_column("assets", "html_status")
