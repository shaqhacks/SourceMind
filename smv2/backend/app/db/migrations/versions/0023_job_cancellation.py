"""jobs.cancel_requested_at for cooperative cancellation

Revision ID: 0023_job_cancellation
Revises: 0022_source_locators
Create Date: 2026-08-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_job_cancellation"
down_revision: str | None = "0022_source_locators"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "cancel_requested_at")
