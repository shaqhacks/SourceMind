from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException

from app.schemas import (
    CurriculumClaimEditIn,
    CurriculumConceptEditIn,
    CurriculumDraftIn,
    CurriculumDraftOut,
    CurriculumExtractionOut,
    CurriculumMergeIn,
    CurriculumSplitIn,
    CurriculumVersionOut,
    EvidenceMappingReviewIn,
    EvidenceMappingReviewOut,
    RelationReviewIn,
    StandardAlignmentIn,
)
from app.services import curriculum_service, llm_readiness_service

router = APIRouter(tags=["curriculum"])


def _raise_curriculum_error(exc: ValueError) -> None:
    if isinstance(exc, curriculum_service.CurriculumNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/courses/{course_id}/curriculum/extract",
    status_code=202,
    response_model=CurriculumExtractionOut,
)
def start_curriculum_extraction(course_id: str) -> CurriculumExtractionOut:
    try:
        job, version = curriculum_service.start_extraction(course_id)
    except llm_readiness_service.LlmReadinessUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return CurriculumExtractionOut(job_id=job.id, curriculum_version_id=version.id)


@router.post(
    "/api/courses/{course_id}/curriculum/drafts",
    status_code=201,
    response_model=CurriculumDraftOut,
)
def create_curriculum_draft(course_id: str, body: CurriculumDraftIn) -> CurriculumDraftOut:
    try:
        version = curriculum_service.create_draft(course_id, label=body.label)
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return CurriculumDraftOut(curriculum_version_id=version.id)


@router.get("/api/courses/{course_id}/curriculum", response_model=CurriculumVersionOut)
def get_curriculum(
    course_id: str, view: Literal["current", "draft"] = "current"
) -> CurriculumVersionOut:
    result = curriculum_service.get_curriculum(course_id, draft=view == "draft")
    if result is None:
        raise HTTPException(status_code=404, detail="curriculum not found")
    return CurriculumVersionOut(**result)


@router.get(
    "/api/courses/{course_id}/curriculum/mappings",
    response_model=list[EvidenceMappingReviewOut],
)
def list_evidence_mappings(course_id: str) -> list[EvidenceMappingReviewOut]:
    return [
        EvidenceMappingReviewOut(**row)
        for row in curriculum_service.list_evidence_mappings(course_id)
    ]


@router.patch(
    "/api/curriculum/mappings/{mapping_id}",
    response_model=EvidenceMappingReviewOut,
)
def review_evidence_mapping(
    mapping_id: str, body: EvidenceMappingReviewIn
) -> EvidenceMappingReviewOut:
    try:
        row = curriculum_service.review_evidence_mapping(mapping_id, body.review_state)
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return EvidenceMappingReviewOut(**row)


@router.patch("/api/curriculum/{version_id}/concepts/{concept_id}")
def edit_concept(
    version_id: str, concept_id: str, body: CurriculumConceptEditIn
) -> dict[str, str]:
    try:
        revision = curriculum_service.edit_concept(
            version_id, concept_id, **body.model_dump()
        )
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return {"concept_id": revision.concept_id}


@router.patch("/api/curriculum/{version_id}/claims/{claim_id}")
def edit_claim(
    version_id: str, claim_id: str, body: CurriculumClaimEditIn
) -> dict[str, str]:
    try:
        revision = curriculum_service.edit_claim(
            version_id, claim_id, **body.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return {"claim_id": revision.learning_claim_id}


@router.post("/api/curriculum/{version_id}/concepts/merge")
def merge_concepts(version_id: str, body: CurriculumMergeIn) -> dict[str, str]:
    try:
        target = curriculum_service.merge_concepts(
            version_id,
            body.source_concept_ids,
            target_concept_id=body.target_concept_id,
        )
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return {"target_concept_id": target.id}


@router.post("/api/curriculum/{version_id}/concepts/{concept_id}/split")
def split_concept(
    version_id: str, concept_id: str, body: CurriculumSplitIn
) -> dict[str, list[str]]:
    try:
        concepts = curriculum_service.split_concept(
            version_id,
            concept_id,
            [child.model_dump() for child in body.children],
        )
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return {"concept_ids": [concept.id for concept in concepts]}


@router.post("/api/curriculum/{version_id}/standards")
def add_standard_alignment(
    version_id: str, body: StandardAlignmentIn
) -> dict[str, str]:
    try:
        relation = curriculum_service.add_relation(
            version_id,
            from_concept_id=body.concept_id,
            kind="aligns_to_standard",
            external_ref=body.external_ref,
            confidence=body.confidence,
            rationale_md=body.rationale_md,
        )
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return {"relation_id": relation.id}


@router.patch("/api/curriculum/relations/{relation_id}")
def review_relation(relation_id: str, body: RelationReviewIn) -> dict[str, str]:
    try:
        relation = curriculum_service.review_relation(relation_id, body.review_state)
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return {"relation_id": relation.id, "review_state": relation.review_state}


@router.post("/api/curriculum/{version_id}/publish")
def publish_curriculum(version_id: str) -> dict[str, str | bool]:
    try:
        version = curriculum_service.publish(version_id)
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return {"curriculum_version_id": version.id, "is_current": version.is_current}


@router.post("/api/curriculum/{version_id}/reject")
def reject_curriculum(version_id: str) -> dict[str, str]:
    try:
        version = curriculum_service.reject(version_id)
    except ValueError as exc:
        _raise_curriculum_error(exc)
    return {"curriculum_version_id": version.id, "status": version.status}
