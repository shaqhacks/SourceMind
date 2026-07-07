"""cards.origin: distinguishes AI-generated cards from user-authored/
user-edited ones (ADR-023) — user-origin cards are preserved untouched by
card-generation's regenerate diff.

Revision ID: 0008_card_origin
Revises: 0007_test_deck_attempt_split
Create Date: 2026-07-07

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_card_origin"
down_revision: Union[str, None] = "0007_test_deck_attempt_split"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain add_column is safe here (no FK, so no batch_alter_table needed
    # — see ADR-019). cards has no triggers today (only
    # sections_body_md_immutable does, scoped to sections) — verified
    # against every prior migration before relying on plain add_column
    # being safe, same check every migration in this series has made.
    op.add_column(
        "cards",
        sa.Column("origin", sa.String(), nullable=False, server_default="generated"),
    )


def downgrade() -> None:
    op.drop_column("cards", "origin")
