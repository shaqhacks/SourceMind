"""immutable evidence item snapshots and claim mappings

Revision ID: 0016_evidence_items
Revises: 0015_versioned_curriculum
Create Date: 2026-08-02

"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_evidence_items"
down_revision: Union[str, None] = "0015_versioned_curriculum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("item_type", sa.String(), nullable=False),
        sa.Column("source_record_id", sa.String(), nullable=False),
        sa.Column("source_index", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_fingerprint", sa.String(), nullable=False),
        sa.Column("mapping_status", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "item_type IN ('quiz_question', 'practice_question', 'flashcard')",
            name="ck_evidence_items_type",
        ),
        sa.CheckConstraint(
            "mapping_status IN ('mapped', 'legacy_unmapped')",
            name="ck_evidence_items_mapping_status",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_type",
            "source_record_id",
            "source_index",
            "content_fingerprint",
            name="uq_evidence_items_source_snapshot",
        ),
    )
    op.create_index("ix_evidence_items_course_id", "evidence_items", ["course_id"])
    op.create_index(
        "ix_evidence_items_source_record_id", "evidence_items", ["source_record_id"]
    )

    op.create_table(
        "evidence_item_concept_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("evidence_item_id", sa.String(), nullable=False),
        sa.Column("curriculum_version_id", sa.String(), nullable=False),
        sa.Column("learning_claim_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("cognitive_demand", sa.String(), nullable=True),
        sa.Column("authored_difficulty_band", sa.String(), nullable=True),
        sa.Column("mapping_confidence", sa.Float(), nullable=True),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("review_state", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('primary', 'supporting', 'prerequisite')",
            name="ck_evidence_item_concept_links_role",
        ),
        sa.CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_evidence_item_concept_links_review_state",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"], ["evidence_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["learning_claim_id"], ["learning_claims.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_item_id",
            "curriculum_version_id",
            "learning_claim_id",
            "role",
            name="uq_evidence_item_concept_links_mapping",
        ),
    )
    for column in (
        "course_id",
        "evidence_item_id",
        "curriculum_version_id",
        "learning_claim_id",
    ):
        op.create_index(
            f"ix_evidence_item_concept_links_{column}",
            "evidence_item_concept_links",
            [column],
        )
    op.create_index(
        "uq_evidence_item_concept_links_primary",
        "evidence_item_concept_links",
        ["evidence_item_id"],
        unique=True,
        sqlite_where=sa.text("role = 'primary' AND review_state != 'rejected'"),
    )
    op.execute(
        """
        CREATE TRIGGER evidence_items_content_immutable
        BEFORE UPDATE OF item_type, source_record_id, source_index, content_json,
                         content_fingerprint ON evidence_items
        BEGIN
            SELECT RAISE(ABORT, 'evidence item content is immutable');
        END;
        """
    )
    _backfill_legacy_items()


def _fingerprint(content: dict[str, Any]) -> str:
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _insert_item(
    bind,
    *,
    course_id: str,
    item_type: str,
    source_record_id: str,
    source_index: int,
    content: dict[str, Any],
    source_ref: str | None,
    prompt_version: str | None,
    model: str | None,
    now: datetime,
) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO evidence_items "
            "(id, course_id, item_type, source_record_id, source_index, content_json, "
            "content_fingerprint, mapping_status, source_ref, prompt_version, model, created_at) "
            "VALUES (:id, :course_id, :item_type, :source_record_id, :source_index, :content, "
            ":fingerprint, 'legacy_unmapped', :source_ref, :prompt_version, :model, :now)"
        ),
        {
            "id": str(uuid.uuid4()),
            "course_id": course_id,
            "item_type": item_type,
            "source_record_id": source_record_id,
            "source_index": source_index,
            "content": json.dumps(content),
            "fingerprint": _fingerprint(content),
            "source_ref": source_ref,
            "prompt_version": prompt_version,
            "model": model,
            "now": now,
        },
    )


def _backfill_legacy_items() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    cards = bind.execute(
        sa.text(
            "SELECT id, course_id, section_id, front_md, back_md, prompt_version FROM cards"
        )
    ).mappings().all()
    for card in cards:
        _insert_item(
            bind,
            course_id=card["course_id"],
            item_type="flashcard",
            source_record_id=card["id"],
            source_index=-1,
            content={"front": card["front_md"], "back": card["back_md"]},
            source_ref=card["section_id"],
            prompt_version=card["prompt_version"],
            model=None,
            now=now,
        )
    tests = bind.execute(
        sa.text(
            "SELECT id, course_id, section_id, chapter_label, questions, "
            "prompt_version, model FROM tests"
        )
    ).mappings().all()
    for test in tests:
        questions = test["questions"]
        if isinstance(questions, str):
            questions = json.loads(questions)
        for index, question in enumerate(questions or []):
            _insert_item(
                bind,
                course_id=test["course_id"],
                item_type="quiz_question",
                source_record_id=test["id"],
                source_index=index,
                content=question,
                source_ref=test["chapter_label"] or test["section_id"],
                prompt_version=test["prompt_version"],
                model=test["model"],
                now=now,
            )
    questions = bind.execute(
        sa.text(
            "SELECT id, course_id, source_ref, stem_md, choices, correct_index, "
            "explanation_md, extraction_version FROM practice_questions"
        )
    ).mappings().all()
    for question in questions:
        choices = question["choices"]
        if isinstance(choices, str):
            choices = json.loads(choices)
        _insert_item(
            bind,
            course_id=question["course_id"],
            item_type="practice_question",
            source_record_id=question["id"],
            source_index=-1,
            content={
                "stem_md": question["stem_md"],
                "choices": choices,
                "correct_index": question["correct_index"],
                "explanation_md": question["explanation_md"],
            },
            source_ref=question["source_ref"],
            prompt_version=question["extraction_version"],
            model=None,
            now=now,
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS evidence_items_content_immutable")
    op.drop_index(
        "uq_evidence_item_concept_links_primary",
        table_name="evidence_item_concept_links",
    )
    for column in (
        "learning_claim_id",
        "curriculum_version_id",
        "evidence_item_id",
        "course_id",
    ):
        op.drop_index(
            f"ix_evidence_item_concept_links_{column}",
            table_name="evidence_item_concept_links",
        )
    op.drop_table("evidence_item_concept_links")
    op.drop_index("ix_evidence_items_source_record_id", table_name="evidence_items")
    op.drop_index("ix_evidence_items_course_id", table_name="evidence_items")
    op.drop_table("evidence_items")
