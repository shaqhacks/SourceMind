"""jobs table

Revision ID: 0001_jobs
Revises:
Create Date: 2026-07-05

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_jobs"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_type", "jobs", ["type"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_type", table_name="jobs")
    op.drop_table("jobs")
