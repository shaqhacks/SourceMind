"""Pure derivation functions for skill graph levels, mastery, and status,
plus the graph import service (top half stays pure/DB-free per the plan)."""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Concept, ConceptEdge, ConceptSectionLink, Section, utcnow

# Constants
QUIZ_WEIGHT = 0.5
PRACTICE_WEIGHT = 0.3
SRS_WEIGHT = 0.2
STRUGGLING_BELOW = 40
SOLID_ABOVE = 70
WEAK_PREREQ_BELOW = 60


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

    # Kahn's algorithm: start with nodes that have no incoming edges (roots)
    queue = [node for node in node_ids if in_degree[node] == 0]
    processed_count = 0

    while queue:
        current = queue.pop(0)
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


def mastery_score(
    practice: float | None, srs: float | None, quiz: float | None
) -> int:
    """
    Calculate mastery score from weighted signals.

    Each signal is in [0, 1] or None. Weights are renormalized over present signals.
    Result is scaled to 0-100 and rounded.

    Args:
        practice: Practice signal (0-1) or None
        srs: SRS signal (0-1) or None
        quiz: Quiz signal (0-1) or None

    Returns:
        Mastery score (0-100), rounded
    """
    if practice is None and srs is None and quiz is None:
        return 0

    # Collect present signals and their weights
    signals = []
    weights = []

    if practice is not None:
        signals.append(practice)
        weights.append(PRACTICE_WEIGHT)

    if srs is not None:
        signals.append(srs)
        weights.append(SRS_WEIGHT)

    if quiz is not None:
        signals.append(quiz)
        weights.append(QUIZ_WEIGHT)

    # Compute weighted sum using original weights
    numerator = sum(s * w for s, w in zip(signals, weights))
    total_weight = sum(weights)

    # Scale to 0-100 and round (multiply by 100 before dividing to minimize precision loss)
    return round((numerator * 100) / total_weight)


def status_for(mastery: int, has_any_signal: bool, weak_prereq: bool) -> str:
    """
    Determine mastery status based on score and prerequisites.

    Status priority:
    1. "locked" if no signal AND weak prerequisite
    2. "growing" if no signal AND no weak prerequisite (new, unblocked learner)
    3. "struggling" if mastery < STRUGGLING_BELOW
    4. "solid" if mastery > SOLID_ABOVE
    5. "growing" otherwise

    Args:
        mastery: Mastery score (0-100)
        has_any_signal: Whether the learner has any recorded signals
        weak_prereq: Whether a prerequisite is below WEAK_PREREQ_BELOW threshold

    Returns:
        Status string: "locked", "struggling", "growing", or "solid"
    """
    # Check locked gate first: no signal AND weak prerequisite blocks access
    if not has_any_signal and weak_prereq:
        return "locked"

    # New learners with no signals are "growing" (unblocked, just starting)
    if not has_any_signal:
        return "growing"

    # Threshold-based status for learners with signals
    if mastery < STRUGGLING_BELOW:
        return "struggling"

    if mastery > SOLID_ABOVE:
        return "solid"

    # Default to growing for those making progress
    return "growing"


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
    """Upserts concepts by (course_id, slug) — keeps existing ids, so
    ConceptMastery survives a re-import — then wholesale deletes and
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
