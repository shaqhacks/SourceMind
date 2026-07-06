"""cards.prompt_version, test_attempts.prompt_version: generated content
rows carry the prompt_version that produced them (previously only
sections.lesson_prompt_version did)

Revision ID: 0003_generated_content_prompt_version
Revises: 0002_domain_schema
Create Date: 2026-07-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_generated_content_prompt_version"
down_revision: Union[str, None] = "0002_domain_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("prompt_version", sa.String(), nullable=True))
    op.add_column("test_attempts", sa.Column("prompt_version", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_attempts", "prompt_version")
    op.drop_column("cards", "prompt_version")
