"""Curriculum graph import and evidence-led learner-state reads."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptEdge,
    ConceptRelation,
    ConceptRevision,
    ConceptSectionLink,
    ConceptSourceLink,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearnerConceptState,
    LearnerEvidenceEvent,
    LearningClaim,
    Section,
    utcnow,
)
from app.services import learner_context

def derive_levels(node_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """
    Compute longest-path depth for each node in a DAG.

    Uses Kahn's algorithm to detect cycles and track the longest path from any root.
    Levels are 1-based (roots start at 1).

    Args:
        node_ids: List of node identifiers
        edges: List of (from, to) tuples representing directed edges

    Returns:
        Dictionary mapping node_id to its level (1-based)

    Raises:
        ValueError: If the graph contains a cycle or an edge references an unknown node
    """
    # Dedupe node_ids while preserving order
    node_ids = list(dict.fromkeys(node_ids))

    # Build adjacency list and track in-degrees
    graph = {node: [] for node in node_ids}
    in_degree = {node: 0 for node in node_ids}

    # Validate that all edge endpoints are in node_ids
    for from_node, to_node in edges:
        if from_node not in graph:
            raise ValueError(f"edge references unknown node: {from_node}")
        if to_node not in graph:
            raise ValueError(f"edge references unknown node: {to_node}")
        graph[from_node].append(to_node)
        in_degree[to_node] += 1

    # Initialize levels (will update with longest paths)
    levels = {node: 0 for node in node_ids}

    # Kahn's algorithm: start with nodes that have no incoming edges (roots).
    # deque so dequeuing is O(1) (popleft) instead of list.pop(0)'s O(n)
    # shift of every remaining element.
    queue = deque(node for node in node_ids if in_degree[node] == 0)
    processed_count = 0

    while queue:
        current = queue.popleft()
        processed_count += 1

        # Set level for current node if not yet set or if this is a longer path
        if levels[current] == 0:
            levels[current] = 1

        # Update all children
        for child in graph[current]:
            # Track longest path to this child
            levels[child] = max(levels[child], levels[current] + 1)

            # Decrease in-degree
            in_degree[child] -= 1

            # If in-degree becomes 0, child is ready to process
            if in_degree[child] == 0:
                queue.append(child)

    # Check for cycle: if not all nodes were processed, there's a cycle
    if processed_count != len(graph):
        raise ValueError("cycle")

    return levels


# --- Graph import (DB-backed; below the pure functions above) --------


class GraphValidationError(ValueError):
    """422: the incoming graph has a cycle, an edge referencing a slug not
    in this same payload's concepts, a duplicate slug, or a section_id that
    doesn't belong to the course."""


def _dedupe_by_key(items: list[dict[str, Any]], key) -> list[dict[str, Any]]:
    """Drops exact duplicates by `key`, first occurrence wins. A repeated
    edge pair or a concept's section_refs repeating the same section_id is
    redundancy in the payload, not a contradiction — silently collapsing it
    keeps import_graph idempotent instead of hitting the DB's unique
    constraints (concept_edges / concept_section_links) with a 500."""
    seen: set[Any] = set()
    result = []
    for item in items:
        k = key(item)
        if k in seen:
            continue
        seen.add(k)
        result.append(item)
    return result


def import_graph(course_id: str, payload: dict[str, Any]) -> dict[str, int]:
    """Upserts concepts by (course_id, slug) — keeping stable ids — then deletes and
    recreates every edge and section link for the course (plan decision
    #3: "idempotent full replace of edges/links, concept upsert").

    Validates the incoming edge set with derive_levels() BEFORE touching
    the DB (cycle / unknown-slug -> GraphValidationError), then checks
    every referenced section_id actually belongs to this course. Exact
    duplicate edges/section_refs are deduped (see _dedupe_by_key) rather
    than rejected — counts in the response reflect the deduped totals.
    """
    concepts_in: list[dict[str, Any]] = payload.get("concepts", [])
    edges_in = _dedupe_by_key(
        payload.get("edges", []), key=lambda e: (e["from_slug"], e["to_slug"])
    )

    slugs = [c["slug"] for c in concepts_in]
    if len(slugs) != len(set(slugs)):
        raise GraphValidationError("duplicate concept slug in payload")

    edge_tuples = [(e["from_slug"], e["to_slug"]) for e in edges_in]
    try:
        derive_levels(slugs, edge_tuples)
    except ValueError as exc:
        raise GraphValidationError(str(exc)) from exc

    # slug -> deduped section_refs, computed once and reused for both the
    # section-ownership check below and the link-creation loop later, so
    # link_count and the actually-inserted rows can never disagree.
    refs_by_slug: dict[str, list[dict[str, Any]]] = {
        c["slug"]: _dedupe_by_key(c.get("section_refs", []), key=lambda r: r["section_id"])
        for c in concepts_in
    }

    section_ids = {ref["section_id"] for refs in refs_by_slug.values() for ref in refs}

    session = get_session()
    try:
        if section_ids:
            valid_section_ids = {
                row[0]
                for row in session.query(Section.id)
                .filter(Section.course_id == course_id, Section.id.in_(section_ids))
                .all()
            }
            missing = section_ids - valid_section_ids
            if missing:
                raise GraphValidationError(
                    f"section {sorted(missing)[0]} does not belong to course {course_id}"
                )

        existing = {
            c.slug: c
            for c in session.query(Concept).filter(Concept.course_id == course_id).all()
        }
        slug_to_id: dict[str, str] = {}
        for c in concepts_in:
            slug = c["slug"]
            concept = existing.get(slug)
            if concept is not None:
                concept.label = c["label"]
                concept.updated_at = utcnow()
            else:
                concept = Concept(course_id=course_id, slug=slug, label=c["label"])
                session.add(concept)
                session.flush()  # assign concept.id for slug_to_id below
            slug_to_id[slug] = concept.id

        session.query(ConceptEdge).filter(ConceptEdge.course_id == course_id).delete()
        for e in edges_in:
            session.add(
                ConceptEdge(
                    course_id=course_id,
                    from_concept_id=slug_to_id[e["from_slug"]],
                    to_concept_id=slug_to_id[e["to_slug"]],
                )
            )

        session.query(ConceptSectionLink).filter(
            ConceptSectionLink.course_id == course_id
        ).delete()
        link_count = 0
        for c in concepts_in:
            concept_id = slug_to_id[c["slug"]]
            for ref in refs_by_slug[c["slug"]]:
                session.add(
                    ConceptSectionLink(
                        course_id=course_id,
                        concept_id=concept_id,
                        section_id=ref["section_id"],
                        rank=ref.get("rank", 0),
                        relevance_md=ref.get("relevance_md"),
                    )
                )
                link_count += 1

        session.commit()
        return {
            "concept_count": len(concepts_in),
            "edge_count": len(edges_in),
            "link_count": link_count,
        }
    finally:
        session.close()


# --- Read assembly (DB-backed) — map + competency detail ---------------


def build_map(
    session, course_id: str, learner_id: str | None = None
) -> dict[str, Any]:
    """Read the current curriculum and its rebuildable learner projection.

    Missing evidence stays nullable. Structural relations may suggest review,
    but they never lock navigation or assert that one concept caused another
    difficulty.
    """
    current_version = session.query(CurriculumVersion).filter_by(
        course_id=course_id, is_current=True
    ).one_or_none()
    current_version_id = current_version.id if current_version is not None else None
    revisions: dict[str, ConceptRevision] = {}
    if current_version_id is not None:
        revisions = {
            revision.concept_id: revision
            for revision in session.query(ConceptRevision).filter(
                ConceptRevision.curriculum_version_id == current_version_id,
                ConceptRevision.is_active.is_(True),
                ConceptRevision.review_state != "rejected",
            )
        }
    concept_query = session.query(Concept).filter(Concept.course_id == course_id)
    if revisions:
        concept_query = concept_query.filter(Concept.id.in_(revisions))
    concepts = concept_query.order_by(Concept.slug).all()
    by_id = {concept.id: concept for concept in concepts}
    concept_ids = list(by_id)
    relation_pairs = []
    if current_version_id is not None:
        relation_pairs = (
            session.query(ConceptRelation.from_concept_id, ConceptRelation.to_concept_id)
            .filter(
                ConceptRelation.curriculum_version_id == current_version_id,
                ConceptRelation.kind == "requires",
                ConceptRelation.review_state != "rejected",
                ConceptRelation.to_concept_id.isnot(None),
            )
            .all()
        )
    if not relation_pairs:
        relation_pairs = [
            (edge.from_concept_id, edge.to_concept_id)
            for edge in session.query(ConceptEdge).filter(ConceptEdge.course_id == course_id)
        ]
    relation_pairs = [
        (from_id, to_id)
        for from_id, to_id in relation_pairs
        if from_id in by_id and to_id in by_id
    ]
    levels = derive_levels(concept_ids, relation_pairs)

    course_profile = (
        learner_context.ensure_course_learning_profile(session, learner_id, course_id)
        if learner_id is not None
        else None
    )
    projection_by_concept: dict[str, LearnerConceptState] = {}
    if current_version_id is not None and course_profile is not None:
        projection_by_concept = {
            state.concept_id: state
            for state in session.query(LearnerConceptState)
            .filter_by(
                course_learning_profile_id=course_profile.id,
                curriculum_version_id=current_version_id,
                state_scope="concept",
                model_version="transparent-beta-v1",
            )
            .all()
        }

    quiz_correct: dict[str, int] = defaultdict(int)
    quiz_wrong: dict[str, int] = defaultdict(int)
    missed_by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if course_profile is not None and current_version_id is not None:
        event_rows = (
            session.query(LearnerEvidenceEvent, EvidenceItem, LearningClaim)
            .join(EvidenceItem, EvidenceItem.id == LearnerEvidenceEvent.evidence_item_id)
            .join(LearningClaim, LearningClaim.id == LearnerEvidenceEvent.learning_claim_id)
            .filter(
                LearnerEvidenceEvent.course_learning_profile_id == course_profile.id,
                LearnerEvidenceEvent.curriculum_version_id == current_version_id,
                LearnerEvidenceEvent.channel == "quiz",
            )
            .order_by(LearnerEvidenceEvent.event_at.desc())
            .all()
        )
        for event, item, claim in event_rows:
            if claim.concept_id not in by_id:
                continue
            if event.normalized_outcome >= 0.5:
                quiz_correct[claim.concept_id] += 1
                continue
            quiz_wrong[claim.concept_id] += 1
            content = item.content_json
            choices = content.get("choices") or []
            selected = (event.raw_result or {}).get("selected_index")
            correct_index = content.get("correct_index")
            missed_by_concept[claim.concept_id].append(
                {
                    "question": str(content.get("question") or content.get("stem_md") or "Question"),
                    "your_answer": (
                        str(choices[selected])
                        if isinstance(selected, int) and 0 <= selected < len(choices)
                        else None
                    ),
                    "correct_answer": (
                        str(choices[correct_index])
                        if isinstance(correct_index, int) and 0 <= correct_index < len(choices)
                        else "See the reviewed answer explanation",
                    ),
                    "source_test_id": item.source_record_id,
                    "attempted_at": event.event_at,
                }
            )

    cards_count: dict[str, int] = defaultdict(int)
    if current_version_id is not None:
        card_rows = (
            session.query(LearningClaim.concept_id)
            .join(
                EvidenceItemConceptLink,
                EvidenceItemConceptLink.learning_claim_id == LearningClaim.id,
            )
            .join(EvidenceItem, EvidenceItem.id == EvidenceItemConceptLink.evidence_item_id)
            .filter(
                EvidenceItem.course_id == course_id,
                EvidenceItem.item_type == "flashcard",
                EvidenceItemConceptLink.curriculum_version_id == current_version_id,
                EvidenceItemConceptLink.role == "primary",
                EvidenceItemConceptLink.review_state == "verified",
            )
            .all()
        )
        for (concept_id,) in card_rows:
            cards_count[concept_id] += 1

    edges_out = []
    for from_concept_id, to_concept_id in relation_pairs:
        predecessor = projection_by_concept.get(from_concept_id)
        kind = (
            "review_suggested"
            if predecessor is None
            or predecessor.status in {"insufficient_evidence", "likely_struggling", "building"}
            else "ready"
        )
        edges_out.append({"from_id": from_concept_id, "to_id": to_concept_id, "kind": kind})

    nodes_out = []
    for concept in concepts:
        projection = projection_by_concept.get(concept.id)
        nodes_out.append(
            {
                "id": concept.id,
                "slug": concept.slug,
                "label": revisions.get(concept.id).label if concept.id in revisions else concept.label,
                "level": levels.get(concept.id, 1),
                "status": projection.status if projection is not None else "insufficient_evidence",
                "readiness_estimate": (
                    projection.readiness_estimate if projection is not None else None
                ),
                "evidence_state": projection.status if projection is not None else "insufficient_evidence",
                "uncertainty": projection.uncertainty if projection is not None else None,
                "posterior_lower": projection.lower_bound if projection is not None else None,
                "posterior_upper": projection.upper_bound if projection is not None else None,
                "quiz_estimate": projection.quiz_estimate if projection is not None else None,
                "review_estimate": projection.review_estimate if projection is not None else None,
                "effective_evidence_count": (
                    projection.effective_evidence_count if projection is not None else 0.0
                ),
                "distinct_item_count": (
                    projection.distinct_item_count if projection is not None else 0
                ),
                "distinct_session_count": (
                    projection.distinct_session_count if projection is not None else 0
                ),
                "trend": projection.trend if projection is not None else "unknown",
                "forgetting_risk": (
                    projection.forgetting_risk if projection is not None else 0.0
                ),
                "last_evidence_at": (
                    projection.last_evidence_at if projection is not None else None
                ),
            }
        )

    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "by_id": by_id,
        "cards_count": cards_count,
        "quiz_correct": quiz_correct,
        "quiz_wrong": quiz_wrong,
        "missed_by_concept": missed_by_concept,
    }


def _taught_in(session, course_id: str, concept_id: str) -> list[dict[str, Any]]:
    rows = (
        session.query(ConceptSectionLink, Section)
        .join(Section, ConceptSectionLink.section_id == Section.id)
        .filter(ConceptSectionLink.concept_id == concept_id)
        .order_by(ConceptSectionLink.rank)
        .all()
    )
    result = [
        {
            "section_id": link.section_id,
            "chapter_label": section.chapter_label,
            "title": section.title,
            "rank": link.rank,
            "relevance_md": link.relevance_md,
        }
        for link, section in rows
    ]
    seen_section_ids = {item["section_id"] for item in result}
    current_version_id = (
        session.query(CurriculumVersion.id)
        .filter_by(course_id=course_id, is_current=True)
        .scalar()
    )
    if current_version_id is not None:
        source_rows = (
            session.query(ConceptSourceLink, Section)
            .join(Section, ConceptSourceLink.section_id == Section.id)
            .filter(
                ConceptSourceLink.curriculum_version_id == current_version_id,
                ConceptSourceLink.concept_id == concept_id,
                ConceptSourceLink.stale.is_(False),
            )
            .order_by(ConceptSourceLink.created_at)
            .all()
        )
        for link, section in source_rows:
            if link.section_id in seen_section_ids:
                continue
            seen_section_ids.add(link.section_id)
            result.append(
                {
                    "section_id": link.section_id,
                    "chapter_label": section.chapter_label,
                    "title": section.title,
                    "rank": len(result),
                    "relevance_md": link.rationale_md,
                }
            )
    return result


def get_skill_map(course_id: str, *, learner_id: str | None = None) -> dict[str, Any]:
    """Router-facing entry point for GET .../skills. Course existence is
    checked by the router (same pattern as list_tests) before this is
    called.
    """
    session = get_session()
    try:
        data = build_map(session, course_id, learner_id)
        return {"nodes": data["nodes"], "edges": data["edges"]}
    finally:
        session.close()


def get_skill_detail(
    course_id: str, concept_id: str, *, learner_id: str | None = None
) -> dict[str, Any] | None:
    """Router-facing entry point for GET .../skills/{concept_id}. Returns
    None when the concept doesn't exist in this course (the router turns
    that into a 404); course existence itself is checked by the router.
    """
    session = get_session()
    try:
        data = build_map(session, course_id, learner_id)
        concept = data["by_id"].get(concept_id)
        if concept is None:
            return None
        node = next(n for n in data["nodes"] if n["id"] == concept_id)

        return {
            "node": node,
            "taught_in": _taught_in(session, course_id, concept_id),
            "missed_questions": data["missed_by_concept"].get(concept_id, []),
            "cards_count": data["cards_count"].get(concept_id, 0),
            "quiz_correct": data["quiz_correct"].get(concept_id, 0),
            "quiz_wrong": data["quiz_wrong"].get(concept_id, 0),
        }
    finally:
        session.close()
