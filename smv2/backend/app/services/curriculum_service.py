from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptRelation,
    ConceptRevision,
    ConceptSourceLink,
    Course,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearningClaim,
    LearningClaimRevision,
    Job,
    utcnow,
)

RELATION_KINDS = {
    "is_part_of",
    "requires",
    "recommended_before",
    "develops_into",
    "related_to",
    "equivalent_to",
    "aligns_to_standard",
}
REVIEW_STATES = {"unverified", "verified", "rejected"}


class CurriculumNotFoundError(ValueError):
    pass


class PublishedCurriculumImmutableError(ValueError):
    pass


class InvalidCurriculumOperationError(ValueError):
    pass


def _draft(session, version_id: str) -> CurriculumVersion:
    version = session.get(CurriculumVersion, version_id)
    if version is None:
        raise CurriculumNotFoundError(f"curriculum version not found: {version_id}")
    if version.status != "draft":
        raise PublishedCurriculumImmutableError(
            f"curriculum version {version_id} is immutable because it is {version.status}"
        )
    return version


def _copy_version_rows(session, source_id: str, target_id: str) -> None:
    for revision in session.query(ConceptRevision).filter_by(
        curriculum_version_id=source_id
    ):
        session.add(
            ConceptRevision(
                curriculum_version_id=target_id,
                concept_id=revision.concept_id,
                label=revision.label,
                description_md=revision.description_md,
                aliases=list(revision.aliases),
                chapter_label=revision.chapter_label,
                review_state=revision.review_state,
                is_active=revision.is_active,
            )
        )
    for revision in session.query(LearningClaimRevision).filter_by(
        curriculum_version_id=source_id
    ):
        session.add(
            LearningClaimRevision(
                curriculum_version_id=target_id,
                learning_claim_id=revision.learning_claim_id,
                concept_id=revision.concept_id,
                statement=revision.statement,
                success_criteria_md=revision.success_criteria_md,
                aliases=list(revision.aliases),
                cognitive_demand=revision.cognitive_demand,
                review_state=revision.review_state,
                is_active=revision.is_active,
            )
        )
    for relation in session.query(ConceptRelation).filter_by(
        curriculum_version_id=source_id
    ):
        session.add(
            ConceptRelation(
                course_id=relation.course_id,
                curriculum_version_id=target_id,
                from_concept_id=relation.from_concept_id,
                to_concept_id=relation.to_concept_id,
                kind=relation.kind,
                external_ref=relation.external_ref,
                confidence=relation.confidence,
                rationale_md=relation.rationale_md,
                review_state=relation.review_state,
            )
        )
    for link in session.query(ConceptSourceLink).filter_by(
        curriculum_version_id=source_id
    ):
        session.add(
            ConceptSourceLink(
                course_id=link.course_id,
                curriculum_version_id=target_id,
                concept_id=link.concept_id,
                learning_claim_id=link.learning_claim_id,
                section_id=link.section_id,
                source_ref=link.source_ref,
                excerpt_md=link.excerpt_md,
                source_content_hash=link.source_content_hash,
                confidence=link.confidence,
                rationale_md=link.rationale_md,
                review_state=link.review_state,
                stale=link.stale,
            )
        )


def create_draft(
    course_id: str, *, based_on_version_id: str | None = None, label: str | None = None
) -> CurriculumVersion:
    session = get_session()
    try:
        if session.get(Course, course_id) is None:
            raise CurriculumNotFoundError(f"course not found: {course_id}")
        source = None
        if based_on_version_id is not None:
            source = session.get(CurriculumVersion, based_on_version_id)
            if source is None or source.course_id != course_id:
                raise CurriculumNotFoundError(
                    f"curriculum version not found for course: {based_on_version_id}"
                )
        else:
            source = (
                session.query(CurriculumVersion)
                .filter_by(course_id=course_id, is_current=True)
                .one_or_none()
            )
        version = CurriculumVersion(
            course_id=course_id,
            parent_version_id=source.id if source is not None else None,
            status="draft",
            is_current=False,
            label=label,
        )
        session.add(version)
        session.flush()
        if source is not None:
            _copy_version_rows(session, source.id, version.id)
        session.commit()
        return version
    finally:
        session.close()


def start_extraction(course_id: str) -> tuple[Job, CurriculumVersion]:
    from app.services import jobs_service, llm_readiness_service

    session = get_session()
    try:
        if session.get(Course, course_id) is None:
            raise CurriculumNotFoundError(f"course not found: {course_id}")
        active_jobs = session.query(Job).filter(
            Job.type == "concept_extraction", Job.status.in_(["queued", "running"])
        )
        for job in active_jobs:
            if (job.payload or {}).get("course_id") == course_id:
                version = session.get(
                    CurriculumVersion, (job.payload or {}).get("curriculum_version_id")
                )
                if version is not None:
                    return job, version

        llm_readiness_service.assert_ready_for_generation()
        version = (
            session.query(CurriculumVersion)
            .filter_by(course_id=course_id, status="draft")
            .order_by(CurriculumVersion.created_at.desc())
            .first()
        )
        if version is None:
            current = session.query(CurriculumVersion).filter_by(
                course_id=course_id, is_current=True
            ).one_or_none()
            version = CurriculumVersion(
                course_id=course_id,
                parent_version_id=current.id if current is not None else None,
                status="draft",
                is_current=False,
                label="Book extraction draft",
            )
            session.add(version)
            session.flush()
            if current is not None:
                _copy_version_rows(session, current.id, version.id)
        job = jobs_service.create_job_in_session(
            session,
            "concept_extraction",
            {"course_id": course_id, "curriculum_version_id": version.id},
        )
        session.commit()
        return job, version
    finally:
        session.close()


def get_curriculum(course_id: str, *, draft: bool = False) -> dict[str, Any] | None:
    session = get_session()
    try:
        query = session.query(CurriculumVersion).filter_by(course_id=course_id)
        if draft:
            version = query.filter_by(status="draft").order_by(
                CurriculumVersion.created_at.desc()
            ).first()
        else:
            version = query.filter_by(is_current=True).one_or_none()
        if version is None:
            return None
        concept_revisions = session.query(ConceptRevision).filter_by(
            curriculum_version_id=version.id
        ).all()
        concepts = {
            concept.id: concept
            for concept in session.query(Concept).filter(
                Concept.id.in_([revision.concept_id for revision in concept_revisions])
            )
        }
        claim_revisions = session.query(LearningClaimRevision).filter_by(
            curriculum_version_id=version.id
        ).all()
        claims = {
            claim.id: claim
            for claim in session.query(LearningClaim).filter(
                LearningClaim.id.in_(
                    [revision.learning_claim_id for revision in claim_revisions]
                )
            )
        }
        return {
            "id": version.id,
            "course_id": version.course_id,
            "parent_version_id": version.parent_version_id,
            "status": version.status,
            "is_current": version.is_current,
            "label": version.label,
            "created_at": version.created_at,
            "published_at": version.published_at,
            "concepts": [
                {
                    "id": revision.concept_id,
                    "stable_key": concepts[revision.concept_id].slug,
                    "label": revision.label,
                    "description_md": revision.description_md,
                    "aliases": revision.aliases,
                    "chapter_label": revision.chapter_label,
                    "review_state": revision.review_state,
                    "is_active": revision.is_active,
                }
                for revision in concept_revisions
            ],
            "claims": [
                {
                    "id": revision.learning_claim_id,
                    "stable_key": claims[revision.learning_claim_id].stable_key,
                    "concept_id": revision.concept_id,
                    "statement": revision.statement,
                    "success_criteria_md": revision.success_criteria_md,
                    "aliases": revision.aliases,
                    "cognitive_demand": revision.cognitive_demand,
                    "review_state": revision.review_state,
                    "is_active": revision.is_active,
                }
                for revision in claim_revisions
            ],
            "relations": [
                {
                    "id": relation.id,
                    "from_concept_id": relation.from_concept_id,
                    "to_concept_id": relation.to_concept_id,
                    "kind": relation.kind,
                    "external_ref": relation.external_ref,
                    "confidence": relation.confidence,
                    "rationale_md": relation.rationale_md,
                    "review_state": relation.review_state,
                }
                for relation in session.query(ConceptRelation).filter_by(
                    curriculum_version_id=version.id
                )
            ],
            "sources": [
                {
                    "id": link.id,
                    "concept_id": link.concept_id,
                    "learning_claim_id": link.learning_claim_id,
                    "section_id": link.section_id,
                    "source_ref": link.source_ref,
                    "excerpt_md": link.excerpt_md,
                    "source_content_hash": link.source_content_hash,
                    "confidence": link.confidence,
                    "rationale_md": link.rationale_md,
                    "review_state": link.review_state,
                    "stale": link.stale,
                }
                for link in session.query(ConceptSourceLink).filter_by(
                    curriculum_version_id=version.id
                )
            ],
        }
    finally:
        session.close()


def list_evidence_mappings(course_id: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        version = session.query(CurriculumVersion).filter_by(
            course_id=course_id, is_current=True
        ).one_or_none()
        if version is None:
            return []
        rows = (
            session.query(
                EvidenceItemConceptLink,
                EvidenceItem,
                LearningClaimRevision,
                ConceptRevision,
            )
            .join(EvidenceItem, EvidenceItem.id == EvidenceItemConceptLink.evidence_item_id)
            .join(
                LearningClaimRevision,
                (LearningClaimRevision.learning_claim_id == EvidenceItemConceptLink.learning_claim_id)
                & (LearningClaimRevision.curriculum_version_id == version.id),
            )
            .join(
                ConceptRevision,
                (ConceptRevision.concept_id == LearningClaimRevision.concept_id)
                & (ConceptRevision.curriculum_version_id == version.id),
            )
            .filter(
                EvidenceItem.course_id == course_id,
                EvidenceItemConceptLink.curriculum_version_id == version.id,
            )
            .order_by(ConceptRevision.label, LearningClaimRevision.statement, EvidenceItem.id)
            .all()
        )
        return [
            {
                "id": mapping.id,
                "evidence_item_id": item.id,
                "item_type": item.item_type,
                "item_preview": str(item.content_json.get("stem_md") or item.content_json.get("front_md") or "")[:240],
                "concept_id": concept.concept_id,
                "concept_label": concept.label,
                "learning_claim_id": claim.learning_claim_id,
                "claim_statement": claim.statement,
                "role": mapping.role,
                "task_type": mapping.task_type,
                "cognitive_demand": mapping.cognitive_demand,
                "mapping_confidence": mapping.mapping_confidence,
                "review_state": mapping.review_state,
                "source_ref": mapping.source_ref,
            }
            for mapping, item, claim, concept in rows
        ]
    finally:
        session.close()


def review_evidence_mapping(mapping_id: str, review_state: str) -> dict[str, Any]:
    if review_state not in {"verified", "rejected"}:
        raise InvalidCurriculumOperationError("mapping review_state must be verified or rejected")
    session = get_session()
    try:
        mapping = session.get(EvidenceItemConceptLink, mapping_id)
        if mapping is None:
            raise CurriculumNotFoundError(f"evidence mapping not found: {mapping_id}")
        mapping.review_state = review_state
        course_id = mapping.course_id
        session.commit()
    finally:
        session.close()
    return next(row for row in list_evidence_mappings(course_id) if row["id"] == mapping_id)


def reject(version_id: str) -> CurriculumVersion:
    session = get_session()
    try:
        version = _draft(session, version_id)
        version.status = "superseded"
        version.is_current = False
        session.commit()
        return version
    finally:
        session.close()


def add_concept(
    version_id: str,
    *,
    stable_key: str,
    label: str,
    description_md: str,
    aliases: list[str] | None = None,
    chapter_label: str | None = None,
    review_state: str = "unverified",
) -> Concept:
    session = get_session()
    try:
        version = _draft(session, version_id)
        concept = (
            session.query(Concept)
            .filter_by(course_id=version.course_id, slug=stable_key)
            .one_or_none()
        )
        if concept is None:
            concept = Concept(
                course_id=version.course_id,
                slug=stable_key,
                label=label,
                chapter_label=chapter_label,
            )
            session.add(concept)
            session.flush()
        existing = session.query(ConceptRevision).filter_by(
            curriculum_version_id=version.id, concept_id=concept.id
        ).one_or_none()
        if existing is not None:
            raise InvalidCurriculumOperationError(
                f"concept {stable_key!r} already exists in curriculum version"
            )
        session.add(
            ConceptRevision(
                curriculum_version_id=version.id,
                concept_id=concept.id,
                label=label,
                description_md=description_md,
                aliases=list(aliases or []),
                chapter_label=chapter_label,
                review_state=review_state,
            )
        )
        session.commit()
        return concept
    finally:
        session.close()


def edit_concept(
    version_id: str,
    concept_id: str,
    *,
    label: str,
    description_md: str,
    aliases: list[str],
    chapter_label: str | None = None,
) -> ConceptRevision:
    session = get_session()
    try:
        _draft(session, version_id)
        revision = session.query(ConceptRevision).filter_by(
            curriculum_version_id=version_id, concept_id=concept_id
        ).one_or_none()
        if revision is None:
            raise CurriculumNotFoundError(f"concept revision not found: {concept_id}")
        revision.label = label
        revision.description_md = description_md
        revision.aliases = list(aliases)
        revision.chapter_label = chapter_label
        concept = session.get(Concept, concept_id)
        assert concept is not None
        concept.label = label
        concept.chapter_label = chapter_label
        session.commit()
        return revision
    finally:
        session.close()


def add_claim(
    version_id: str,
    *,
    concept_id: str,
    stable_key: str,
    statement: str,
    success_criteria_md: str,
    cognitive_demand: str | None = None,
    aliases: list[str] | None = None,
    review_state: str = "unverified",
) -> LearningClaim:
    session = get_session()
    try:
        version = _draft(session, version_id)
        concept = session.get(Concept, concept_id)
        if concept is None or concept.course_id != version.course_id:
            raise CurriculumNotFoundError(f"concept not found for curriculum: {concept_id}")
        claim = (
            session.query(LearningClaim)
            .filter_by(course_id=version.course_id, stable_key=stable_key)
            .one_or_none()
        )
        if claim is None:
            claim = LearningClaim(
                course_id=version.course_id,
                concept_id=concept_id,
                stable_key=stable_key,
            )
            session.add(claim)
            session.flush()
        session.add(
            LearningClaimRevision(
                curriculum_version_id=version.id,
                learning_claim_id=claim.id,
                concept_id=concept_id,
                statement=statement,
                success_criteria_md=success_criteria_md,
                aliases=list(aliases or []),
                cognitive_demand=cognitive_demand,
                review_state=review_state,
            )
        )
        session.commit()
        return claim
    finally:
        session.close()


def edit_claim(version_id: str, claim_id: str, **changes: Any) -> LearningClaimRevision:
    allowed = {
        "concept_id",
        "statement",
        "success_criteria_md",
        "aliases",
        "cognitive_demand",
        "review_state",
        "is_active",
    }
    if unknown := set(changes) - allowed:
        raise InvalidCurriculumOperationError(f"unsupported claim fields: {sorted(unknown)}")
    session = get_session()
    try:
        _draft(session, version_id)
        revision = session.query(LearningClaimRevision).filter_by(
            curriculum_version_id=version_id, learning_claim_id=claim_id
        ).one_or_none()
        if revision is None:
            raise CurriculumNotFoundError(f"learning claim revision not found: {claim_id}")
        for field, value in changes.items():
            setattr(revision, field, list(value) if field == "aliases" else value)
        session.commit()
        return revision
    finally:
        session.close()


def add_relation(
    version_id: str,
    *,
    from_concept_id: str,
    kind: str,
    to_concept_id: str | None = None,
    external_ref: str | None = None,
    confidence: float | None = None,
    rationale_md: str | None = None,
) -> ConceptRelation:
    if kind not in RELATION_KINDS:
        raise InvalidCurriculumOperationError(f"unsupported relation kind: {kind}")
    if to_concept_id is None and not (kind == "aligns_to_standard" and external_ref):
        raise InvalidCurriculumOperationError("relation requires a target concept or standard")
    session = get_session()
    try:
        version = _draft(session, version_id)
        relation = ConceptRelation(
            course_id=version.course_id,
            curriculum_version_id=version.id,
            from_concept_id=from_concept_id,
            to_concept_id=to_concept_id,
            kind=kind,
            external_ref=external_ref,
            confidence=confidence,
            rationale_md=rationale_md,
            review_state="unverified",
        )
        session.add(relation)
        session.commit()
        return relation
    finally:
        session.close()


def review_relation(relation_id: str, review_state: str) -> ConceptRelation:
    if review_state not in REVIEW_STATES:
        raise InvalidCurriculumOperationError(f"unsupported review state: {review_state}")
    session = get_session()
    try:
        relation = session.get(ConceptRelation, relation_id)
        if relation is None:
            raise CurriculumNotFoundError(f"concept relation not found: {relation_id}")
        _draft(session, relation.curriculum_version_id)
        relation.review_state = review_state
        session.commit()
        return relation
    finally:
        session.close()


def merge_concepts(
    version_id: str, source_concept_ids: list[str], *, target_concept_id: str
) -> Concept:
    session = get_session()
    try:
        version = _draft(session, version_id)
        target = session.get(Concept, target_concept_id)
        if target is None or target.course_id != version.course_id:
            raise CurriculumNotFoundError(f"target concept not found: {target_concept_id}")
        for source_id in source_concept_ids:
            if source_id == target_concept_id:
                continue
            source = session.get(Concept, source_id)
            revision = session.query(ConceptRevision).filter_by(
                curriculum_version_id=version.id, concept_id=source_id
            ).one_or_none()
            if source is None or revision is None or source.course_id != version.course_id:
                raise CurriculumNotFoundError(f"source concept not found: {source_id}")
            source.merged_into_concept_id = target_concept_id
            revision.is_active = False
        session.commit()
        return target
    finally:
        session.close()


def split_concept(
    version_id: str, concept_id: str, children: list[dict[str, str]]
) -> list[Concept]:
    if len(children) < 2:
        raise InvalidCurriculumOperationError("a split requires at least two child concepts")
    session = get_session()
    try:
        version = _draft(session, version_id)
        original_revision = session.query(ConceptRevision).filter_by(
            curriculum_version_id=version.id, concept_id=concept_id
        ).one_or_none()
        if original_revision is None:
            raise CurriculumNotFoundError(f"concept revision not found: {concept_id}")
        original_revision.is_active = False
        created: list[Concept] = []
        for child in children:
            concept = Concept(
                course_id=version.course_id,
                slug=child["stable_key"],
                label=child["label"],
                chapter_label=original_revision.chapter_label,
            )
            session.add(concept)
            session.flush()
            session.add(
                ConceptRevision(
                    curriculum_version_id=version.id,
                    concept_id=concept.id,
                    label=child["label"],
                    description_md=child.get("description_md", ""),
                    aliases=[],
                    chapter_label=original_revision.chapter_label,
                    review_state="unverified",
                )
            )
            created.append(concept)
        session.commit()
        return created
    finally:
        session.close()


def publish(version_id: str) -> CurriculumVersion:
    session = get_session()
    try:
        version = _draft(session, version_id)
        (
            session.query(CurriculumVersion)
            .filter(
                CurriculumVersion.course_id == version.course_id,
                CurriculumVersion.is_current.is_(True),
            )
            .update(
                {CurriculumVersion.is_current: False, CurriculumVersion.status: "superseded"},
                synchronize_session=False,
            )
        )
        session.flush()
        version.status = "published"
        version.is_current = True
        version.published_at = utcnow()
        session.commit()
        return version
    finally:
        session.close()
