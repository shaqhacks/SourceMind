"""ops-substrate schema fixes: course timestamps, drop dead chapters.assets

- courses.created_at / courses.updated_at: String -> DateTime, with a
  server_default of CURRENT_TIMESTAMP (updated_at additionally gets an
  ORM-level onupdate, which is not a DDL concern and needs no migration step).
- chapters.assets: dropped. It was always JSON-null (never written by the
  ingest pipeline — asset records live in the ``assets`` table instead) and
  is no longer part of the ORM model.

Both operations use batch mode because SQLite cannot ALTER COLUMN or DROP
COLUMN in place; batch mode recreates each table and copies its data.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("courses") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.String(),
            type_=sa.DateTime(),
            server_default=sa.func.now(),
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.String(),
            type_=sa.DateTime(),
            server_default=sa.func.now(),
        )

    with op.batch_alter_table("chapters") as batch_op:
        batch_op.drop_column("assets")


def downgrade() -> None:
    with op.batch_alter_table("chapters") as batch_op:
        batch_op.add_column(sa.Column("assets", sa.JSON(), nullable=True))

    with op.batch_alter_table("courses") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            type_=sa.String(),
            server_default=None,
        )
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            type_=sa.String(),
            server_default=None,
        )
