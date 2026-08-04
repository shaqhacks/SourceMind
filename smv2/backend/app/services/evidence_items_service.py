from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    ConceptSourceLink,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearningClaim,
    LearningClaimRevision,
)


def content_fingerprint(content: dict[str, Any]) -> str:
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def claim_options_for_sections(
    session: Session, course_id: str, section_ids: list[str]
) -> tuple[str | None, list[dict[str, Any]]]:
    version_id = (
        session.query(CurriculumVersion.id)
        .filter_by(course_id=course_id, is_current=True)
        .scalar()
    )
    if version_id is None or not section_ids:
        return version_id, []
    rows = (
        session.query(LearningClaim, LearningClaimRevision, ConceptSourceLink)
        .join(
            LearningClaimRevision,
            LearningClaimRevision.learning_claim_id == LearningClaim.id,
        )
        .join(
            ConceptSourceLink,
            ConceptSourceLink.learning_claim_id == LearningClaim.id,
        )
        .filter(
            LearningClaim.course_id == course_id,
            LearningClaimRevision.curriculum_version_id == version_id,
            LearningClaimRevision.is_active.is_(True),
            LearningClaimRevision.review_state != "rejected",
            ConceptSourceLink.curriculum_version_id == version_id,
            ConceptSourceLink.section_id.in_(section_ids),
            ConceptSourceLink.stale.is_(False),
            ConceptSourceLink.review_state != "rejected",
        )
        .all()
    )
    options: dict[str, dict[str, Any]] = {}
    for claim, revision, source in rows:
        options[claim.id] = {
            "claim_id": claim.id,
            "concept_id": revision.concept_id,
            "statement": revision.statement,
            "success_criteria_md": revision.success_criteria_md,
            "cognitive_demand": revision.cognitive_demand,
            "source_ref": source.source_ref,
        }
    return version_id, list(options.values())


def snapshot_item(
    session: Session,
    *,
    course_id: str,
    item_type: str,
    source_record_id: str,
    source_index: int,
    content: dict[str, Any],
    source_ref: str | None,
    prompt_version: str | None,
    model: str | None,
) -> EvidenceItem:
    fingerprint = content_fingerprint(content)
    item = session.query(EvidenceItem).filter_by(
        item_type=item_type,
        source_record_id=source_record_id,
        source_index=source_index,
        content_fingerprint=fingerprint,
    ).one_or_none()
    if item is None:
        item = EvidenceItem(
            course_id=course_id,
            item_type=item_type,
            source_record_id=source_record_id,
            source_index=source_index,
            content_json=content,
            content_fingerprint=fingerprint,
            mapping_status="legacy_unmapped",
            source_ref=source_ref,
            prompt_version=prompt_version,
            model=model,
        )
        session.add(item)
        session.flush()
    return item


def map_item_to_claim(
    session: Session,
    item: EvidenceItem,
    *,
    curriculum_version_id: str,
    learning_claim_id: str,
    role: str = "primary",
    task_type: str,
    cognitive_demand: str | None,
    authored_difficulty_band: str | None,
    mapping_confidence: float | None,
    source_ref: str | None,
    prompt_version: str | None,
    model: str | None,
    review_state: str = "unverified",
) -> EvidenceItemConceptLink:
    version = session.get(CurriculumVersion, curriculum_version_id)
    claim = session.get(LearningClaim, learning_claim_id)
    if (
        version is None
        or claim is None
        or version.course_id != item.course_id
        or claim.course_id != item.course_id
    ):
        raise ValueError("evidence mapping must stay within one course")
    existing = session.query(EvidenceItemConceptLink).filter_by(
        evidence_item_id=item.id,
        curriculum_version_id=curriculum_version_id,
        learning_claim_id=learning_claim_id,
        role=role,
    ).one_or_none()
    if existing is not None:
        return existing
    link = EvidenceItemConceptLink(
        course_id=item.course_id,
        evidence_item_id=item.id,
        curriculum_version_id=curriculum_version_id,
        learning_claim_id=learning_claim_id,
        role=role,
        task_type=task_type,
        cognitive_demand=cognitive_demand,
        authored_difficulty_band=authored_difficulty_band,
        mapping_confidence=mapping_confidence,
        source_ref=source_ref,
        prompt_version=prompt_version,
        model=model,
        review_state=review_state,
    )
    session.add(link)
    item.mapping_status = "mapped"
    session.flush()
    return link
