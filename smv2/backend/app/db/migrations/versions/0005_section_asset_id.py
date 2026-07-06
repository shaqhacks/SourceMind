"""sections.asset_id: which uploaded PDF a section's text came from, so the
reader can offer an original-PDF page view (owner request).

Revision ID: 0005_section_asset_id
Revises: 0004_section_kind_chapter_label
Create Date: 2026-07-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_section_asset_id"
down_revision: Union[str, None] = "0004_section_kind_chapter_label"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BODY_MD_IMMUTABLE_TRIGGER = """
    CREATE TRIGGER sections_body_md_immutable
    BEFORE UPDATE OF body_md ON sections
    WHEN NEW.body_md IS NOT OLD.body_md
    BEGIN
        SELECT RAISE(ABORT, 'body_md is immutable');
    END;
"""


def upgrade() -> None:
    # SQLite can't ALTER a table to add a new FK constraint in place (only
    # plain ADD COLUMN, no inline REFERENCES enforcement) — batch mode does
    # the standard SQLite workaround (new table, copy, drop, rename) under
    # the hood. Plain op.add_column(..., sa.ForeignKey(...)) raises
    # NotImplementedError on this dialect; verified while writing this
    # migration.
    #
    # CRITICAL: that rebuild drops the OLD sections table, and with it the
    # sections_body_md_immutable trigger from migration 0002 — SQLite
    # triggers don't survive their target table being dropped, even though
    # a same-named table exists again immediately after. Recreating the
    # trigger here is not optional; verified live that skipping this step
    # silently disables body_md immutability enforcement for any DB that
    # runs this migration (test_body_md_immutable.py caught it).
    with op.batch_alter_table("sections") as batch_op:
        batch_op.add_column(sa.Column("asset_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_sections_asset_id_assets",
            "assets",
            ["asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(_BODY_MD_IMMUTABLE_TRIGGER)


def downgrade() -> None:
    with op.batch_alter_table("sections") as batch_op:
        batch_op.drop_constraint("fk_sections_asset_id_assets", type_="foreignkey")
        batch_op.drop_column("asset_id")
    # Same reasoning as upgrade(): the rebuild drops the trigger, so it must
    # be recreated here too, or downgrading leaves body_md unprotected.
    op.execute(_BODY_MD_IMMUTABLE_TRIGGER)
