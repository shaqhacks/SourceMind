"""versioned curriculum concepts, claims, relations, and source provenance

Revision ID: 0015_versioned_curriculum
Revises: 0014_learner_profiles
Create Date: 2026-08-02

"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_versioned_curriculum"
down_revision: Union[str, None] = "0014_learner_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _legacy_version_id(course_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sourcemind:legacy-curriculum:{course_id}"))


def upgrade() -> None:
    with op.batch_alter_table("concepts") as batch_op:
        batch_op.add_column(sa.Column("merged_into_concept_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_concepts_merged_into_concept_id",
            "concepts",
            ["merged_into_concept_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "curriculum_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("parent_version_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'superseded')",
            name="ck_curriculum_versions_status",
        ),
        sa.CheckConstraint(
            "is_current = 0 OR status = 'published'",
            name="ck_curriculum_versions_current_published",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["curriculum_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_curriculum_versions_course_id", "curriculum_versions", ["course_id"])
    op.create_index(
        "uq_curriculum_versions_current_course",
        "curriculum_versions",
        ["course_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )

    op.create_table(
        "concept_revisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("curriculum_version_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("description_md", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("chapter_label", sa.String(), nullable=True),
        sa.Column("review_state", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_concept_revisions_review_state",
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "curriculum_version_id",
            "concept_id",
            name="uq_concept_revisions_version_concept",
        ),
    )
    op.create_index(
        "ix_concept_revisions_curriculum_version_id",
        "concept_revisions",
        ["curriculum_version_id"],
    )
    op.create_index("ix_concept_revisions_concept_id", "concept_revisions", ["concept_id"])

    op.create_table(
        "learning_claims",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("stable_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "stable_key", name="uq_learning_claims_course_key"),
    )
    op.create_index("ix_learning_claims_course_id", "learning_claims", ["course_id"])
    op.create_index("ix_learning_claims_concept_id", "learning_claims", ["concept_id"])

    op.create_table(
        "learning_claim_revisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("curriculum_version_id", sa.String(), nullable=False),
        sa.Column("learning_claim_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("success_criteria_md", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("cognitive_demand", sa.String(), nullable=True),
        sa.Column("review_state", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_learning_claim_revisions_review_state",
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["learning_claim_id"], ["learning_claims.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "curriculum_version_id",
            "learning_claim_id",
            name="uq_learning_claim_revisions_version_claim",
        ),
    )
    op.create_index(
        "ix_learning_claim_revisions_curriculum_version_id",
        "learning_claim_revisions",
        ["curriculum_version_id"],
    )
    op.create_index(
        "ix_learning_claim_revisions_learning_claim_id",
        "learning_claim_revisions",
        ["learning_claim_id"],
    )
    op.create_index(
        "ix_learning_claim_revisions_concept_id",
        "learning_claim_revisions",
        ["concept_id"],
    )

    op.create_table(
        "concept_relations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("curriculum_version_id", sa.String(), nullable=False),
        sa.Column("from_concept_id", sa.String(), nullable=False),
        sa.Column("to_concept_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("external_ref", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale_md", sa.Text(), nullable=True),
        sa.Column("review_state", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('is_part_of', 'requires', 'recommended_before', "
            "'develops_into', 'related_to', 'equivalent_to', 'aligns_to_standard')",
            name="ck_concept_relations_kind",
        ),
        sa.CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_concept_relations_review_state",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["from_concept_id"], ["concepts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["to_concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "curriculum_version_id",
            "from_concept_id",
            "to_concept_id",
            "kind",
            name="uq_concept_relations_version_pair_kind",
        ),
    )
    for column in (
        "course_id",
        "curriculum_version_id",
        "from_concept_id",
        "to_concept_id",
    ):
        op.create_index(f"ix_concept_relations_{column}", "concept_relations", [column])

    op.create_table(
        "concept_source_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("curriculum_version_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("learning_claim_id", sa.String(), nullable=True),
        sa.Column("section_id", sa.String(), nullable=True),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("excerpt_md", sa.Text(), nullable=True),
        sa.Column("source_content_hash", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale_md", sa.Text(), nullable=True),
        sa.Column("review_state", sa.String(), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_concept_source_links_review_state",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["learning_claim_id"], ["learning_claims.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "course_id",
        "curriculum_version_id",
        "concept_id",
        "learning_claim_id",
        "section_id",
    ):
        op.create_index(f"ix_concept_source_links_{column}", "concept_source_links", [column])

    _backfill_legacy_curriculum()


def _backfill_legacy_curriculum() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    course_ids = [
        row[0]
        for row in bind.execute(sa.text("SELECT DISTINCT course_id FROM concepts")).fetchall()
    ]
    for course_id in course_ids:
        version_id = _legacy_version_id(course_id)
        bind.execute(
            sa.text(
                "INSERT INTO curriculum_versions "
                "(id, course_id, parent_version_id, status, is_current, label, created_at, published_at) "
                "VALUES (:id, :course_id, NULL, 'published', 1, 'Legacy import', :now, :now)"
            ),
            {"id": version_id, "course_id": course_id, "now": now},
        )
        concepts = bind.execute(
            sa.text(
                "SELECT id, label, chapter_label, section_id FROM concepts "
                "WHERE course_id = :course_id"
            ),
            {"course_id": course_id},
        ).mappings().all()
        for concept in concepts:
            bind.execute(
                sa.text(
                    "INSERT INTO concept_revisions "
                    "(id, curriculum_version_id, concept_id, label, description_md, aliases, "
                    "chapter_label, review_state, is_active, created_at) "
                    "VALUES (:id, :version_id, :concept_id, :label, '', '[]', :chapter_label, "
                    "'unverified', 1, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "version_id": version_id,
                    "concept_id": concept["id"],
                    "label": concept["label"],
                    "chapter_label": concept["chapter_label"],
                    "now": now,
                },
            )

        edges = bind.execute(
            sa.text(
                "SELECT from_concept_id, to_concept_id FROM concept_edges "
                "WHERE course_id = :course_id"
            ),
            {"course_id": course_id},
        ).mappings().all()
        for edge in edges:
            bind.execute(
                sa.text(
                    "INSERT INTO concept_relations "
                    "(id, course_id, curriculum_version_id, from_concept_id, to_concept_id, "
                    "kind, external_ref, confidence, rationale_md, review_state, created_at) "
                    "VALUES (:id, :course_id, :version_id, :from_id, :to_id, 'requires', "
                    "NULL, NULL, 'Imported from legacy prerequisite graph.', 'unverified', :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "course_id": course_id,
                    "version_id": version_id,
                    "from_id": edge["from_concept_id"],
                    "to_id": edge["to_concept_id"],
                    "now": now,
                },
            )

        source_rows = bind.execute(
            sa.text(
                "SELECT c.id AS concept_id, s.id AS section_id, s.title, s.body_md, "
                "s.content_hash FROM concepts c JOIN sections s ON s.id = c.section_id "
                "WHERE c.course_id = :course_id "
                "UNION SELECT l.concept_id, s.id, s.title, s.body_md, s.content_hash "
                "FROM concept_section_links l JOIN sections s ON s.id = l.section_id "
                "WHERE l.course_id = :course_id"
            ),
            {"course_id": course_id},
        ).mappings().all()
        for source in source_rows:
            bind.execute(
                sa.text(
                    "INSERT INTO concept_source_links "
                    "(id, course_id, curriculum_version_id, concept_id, learning_claim_id, "
                    "section_id, source_ref, excerpt_md, source_content_hash, confidence, "
                    "rationale_md, review_state, stale, created_at) "
                    "VALUES (:id, :course_id, :version_id, :concept_id, NULL, :section_id, "
                    ":source_ref, :excerpt, :content_hash, NULL, "
                    "'Imported from legacy section attribution.', 'unverified', 0, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "course_id": course_id,
                    "version_id": version_id,
                    "concept_id": source["concept_id"],
                    "section_id": source["section_id"],
                    "source_ref": source["title"] or source["section_id"],
                    "excerpt": (source["body_md"] or "")[:500],
                    "content_hash": source["content_hash"],
                    "now": now,
                },
            )


def downgrade() -> None:
    for column in (
        "section_id",
        "learning_claim_id",
        "concept_id",
        "curriculum_version_id",
        "course_id",
    ):
        op.drop_index(f"ix_concept_source_links_{column}", table_name="concept_source_links")
    op.drop_table("concept_source_links")

    for column in (
        "to_concept_id",
        "from_concept_id",
        "curriculum_version_id",
        "course_id",
    ):
        op.drop_index(f"ix_concept_relations_{column}", table_name="concept_relations")
    op.drop_table("concept_relations")
    op.drop_index(
        "ix_learning_claim_revisions_concept_id", table_name="learning_claim_revisions"
    )
    op.drop_index(
        "ix_learning_claim_revisions_learning_claim_id",
        table_name="learning_claim_revisions",
    )
    op.drop_index(
        "ix_learning_claim_revisions_curriculum_version_id",
        table_name="learning_claim_revisions",
    )
    op.drop_table("learning_claim_revisions")
    op.drop_index("ix_learning_claims_concept_id", table_name="learning_claims")
    op.drop_index("ix_learning_claims_course_id", table_name="learning_claims")
    op.drop_table("learning_claims")
    op.drop_index("ix_concept_revisions_concept_id", table_name="concept_revisions")
    op.drop_index(
        "ix_concept_revisions_curriculum_version_id", table_name="concept_revisions"
    )
    op.drop_table("concept_revisions")
    op.drop_index(
        "uq_curriculum_versions_current_course", table_name="curriculum_versions"
    )
    op.drop_index("ix_curriculum_versions_course_id", table_name="curriculum_versions")
    op.drop_table("curriculum_versions")
    with op.batch_alter_table("concepts") as batch_op:
        batch_op.drop_constraint("fk_concepts_merged_into_concept_id", type_="foreignkey")
        batch_op.drop_column("merged_into_concept_id")
