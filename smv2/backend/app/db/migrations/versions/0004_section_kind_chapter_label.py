"""sections.kind, sections.chapter_label, test_attempts.chapter_label:
practice-sheet/answer-key classification and chapter grouping (ADR-017).

Revision ID: 0004_section_kind_chapter_label
Revises: 0003_generated_content_prompt_version
Create Date: 2026-07-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_section_kind_chapter_label"
down_revision: Union[str, None] = "0003_generated_content_prompt_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sections",
        sa.Column("kind", sa.String(), nullable=False, server_default="content"),
    )
    op.add_column("sections", sa.Column("chapter_label", sa.String(), nullable=True))
    op.add_column("test_attempts", sa.Column("chapter_label", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_attempts", "chapter_label")
    op.drop_column("sections", "chapter_label")
    op.drop_column("sections", "kind")
