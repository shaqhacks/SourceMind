"""Pure derivation functions for skill graph levels, mastery, and status,
plus the graph import service (top half stays pure/DB-free per the plan)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.db.engine import get_session
from app.db.models import (
    Card,
    Concept,
    ConceptEdge,
    ConceptMastery,
    ConceptSectionLink,
    ReviewState,
    Section,
    Test,
    TestAttempt,
    utcnow,
)

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


# --- Read assembly (DB-backed) — map + competency detail ---------------


def _test_scope_section_ids(
    test: Test,
    sections_by_chapter: dict[str | None, list[Section]],
    all_section_ids: list[str],
) -> list[str]:
    """Mirrors tests_service's scope resolution (start_test_generation /
    _resolve_missed_card_section_id): an explicit single-section test uses
    just that section; a chapter-scoped test uses every non-answer-key
    section of that chapter; otherwise every section in the course.
    """
    if test.section_id is not None:
        return [test.section_id]
    if test.chapter_label is not None:
        return [
            s.id for s in sections_by_chapter.get(test.chapter_label, []) if s.kind != "answers"
        ]
    return list(all_section_ids)


def build_map(session, course_id: str) -> dict[str, Any]:
    """Assembles the full competency graph for a course: nodes/edges (the
    public map shape) plus the per-concept signal internals that
    get_skill_detail reuses without re-querying. This is the single
    shared assembly function both read endpoints delegate to.

    Includes ALL concepts of the course, even ones with no edges or
    section links (stale/unlinked concepts persist by design — the graph
    import upserts, it never deletes a concept dropped from a later
    import).
    """
    concepts = (
        session.query(Concept).filter(Concept.course_id == course_id).order_by(Concept.slug).all()
    )
    by_id = {c.id: c for c in concepts}
    concept_ids = [c.id for c in concepts]

    edges = session.query(ConceptEdge).filter(ConceptEdge.course_id == course_id).all()
    levels = derive_levels(concept_ids, [(e.from_concept_id, e.to_concept_id) for e in edges])

    links = (
        session.query(ConceptSectionLink).filter(ConceptSectionLink.course_id == course_id).all()
    )
    links_by_concept: dict[str, list[ConceptSectionLink]] = defaultdict(list)
    for link in links:
        links_by_concept[link.concept_id].append(link)
    link_section_ids_by_concept = {
        cid: {link.section_id for link in links_by_concept.get(cid, [])} for cid in concept_ids
    }

    practice_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for m in session.query(ConceptMastery).filter(ConceptMastery.course_id == course_id).all():
        totals = practice_totals[m.concept_id]
        totals[0] += m.correct_count
        totals[1] += m.wrong_count

    cards_by_section: dict[str, list[Card]] = defaultdict(list)
    for c in session.query(Card).filter(Card.course_id == course_id).all():
        cards_by_section[c.section_id].append(c)
    review_by_card = {
        r.card_id: r
        for r in session.query(ReviewState).filter(ReviewState.course_id == course_id).all()
    }

    sections = session.query(Section).filter(Section.course_id == course_id).all()
    sections_by_chapter: dict[str | None, list[Section]] = defaultdict(list)
    for s in sections:
        sections_by_chapter[s.chapter_label].append(s)
    all_section_ids = [s.id for s in sections]

    # test_id -> (test, latest graded attempt, its scope section ids). Only
    # graded (submitted) attempts carry a signal; when a test has none it
    # contributes nothing. "Latest" resolves the brief's silence on which
    # attempt feeds the tally the same way it's resolved for
    # missed_questions, per the task's own controller ruling.
    graded_attempts_by_test: dict[str, list[TestAttempt]] = defaultdict(list)
    for a in (
        session.query(TestAttempt)
        .filter(TestAttempt.course_id == course_id, TestAttempt.results.isnot(None))
        .all()
    ):
        graded_attempts_by_test[a.test_id].append(a)

    latest_by_test: dict[str, tuple[Test, TestAttempt, set[str]]] = {}
    for test in session.query(Test).filter(Test.course_id == course_id).all():
        candidates = graded_attempts_by_test.get(test.id, [])
        if not candidates:
            continue
        latest = max(candidates, key=lambda a: a.created_at)
        scope_ids = set(_test_scope_section_ids(test, sections_by_chapter, all_section_ids))
        latest_by_test[test.id] = (test, latest, scope_ids)

    quiz_correct: dict[str, int] = defaultdict(int)
    quiz_wrong: dict[str, int] = defaultdict(int)
    quiz_tests_by_concept: dict[str, list[tuple[Test, TestAttempt]]] = defaultdict(list)
    for concept_id, section_ids in link_section_ids_by_concept.items():
        for test, latest, scope_ids in latest_by_test.values():
            if not (section_ids & scope_ids):
                continue
            quiz_tests_by_concept[concept_id].append((test, latest))
            for result in latest.results:
                if result["correct"]:
                    quiz_correct[concept_id] += 1
                else:
                    quiz_wrong[concept_id] += 1

    mastery: dict[str, int] = {}
    has_signal: dict[str, bool] = {}
    cards_count: dict[str, int] = {}
    for concept in concepts:
        srs_section_ids = set(link_section_ids_by_concept[concept.id])
        if concept.section_id:
            srs_section_ids.add(concept.section_id)
        concept_cards = [c for sid in srs_section_ids for c in cards_by_section.get(sid, [])]
        cards_count[concept.id] = len(concept_cards)

        grades = [
            min(1.0, max(0.0, (review_by_card[c.id].last_grade - 1) / 3))
            for c in concept_cards
            if c.id in review_by_card and review_by_card[c.id].last_grade is not None
        ]
        srs = sum(grades) / len(grades) if grades else None

        pt = practice_totals.get(concept.id)
        practice = pt[0] / (pt[0] + pt[1]) if pt and (pt[0] + pt[1]) > 0 else None

        qc, qw = quiz_correct.get(concept.id, 0), quiz_wrong.get(concept.id, 0)
        quiz = qc / (qc + qw) if (qc + qw) > 0 else None

        mastery[concept.id] = mastery_score(practice, srs, quiz)
        has_signal[concept.id] = practice is not None or srs is not None or quiz is not None

    edges_out = []
    incoming_weak: dict[str, list[str]] = defaultdict(list)
    outgoing_weak: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        kind = "weak" if mastery[e.from_concept_id] < WEAK_PREREQ_BELOW else "met"
        edges_out.append({"from_id": e.from_concept_id, "to_id": e.to_concept_id, "kind": kind})
        if kind == "weak":
            incoming_weak[e.to_concept_id].append(e.from_concept_id)
            outgoing_weak[e.from_concept_id].append(e.to_concept_id)

    nodes_out = []
    weakest_prereq_by_concept: dict[str, Concept | None] = {}
    for concept in concepts:
        weak_prereq_ids = incoming_weak.get(concept.id, [])
        status = status_for(mastery[concept.id], has_signal[concept.id], bool(weak_prereq_ids))
        blocked = status == "locked"

        weakest = None
        if weak_prereq_ids:
            weakest = min((by_id[pid] for pid in weak_prereq_ids), key=lambda p: (mastery[p.id], p.id))
        weakest_prereq_by_concept[concept.id] = weakest

        unlock_note = (
            f"Unlocks at {WEAK_PREREQ_BELOW} mastery of {weakest.label}"
            if blocked and weakest is not None
            else None
        )

        nodes_out.append(
            {
                "id": concept.id,
                "slug": concept.slug,
                "label": concept.label,
                "level": levels.get(concept.id, 1),
                "mastery": mastery[concept.id],
                "status": status,
                "blocked": blocked,
                "unlock_note": unlock_note,
            }
        )

    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "by_id": by_id,
        "cards_count": cards_count,
        "quiz_correct": quiz_correct,
        "quiz_wrong": quiz_wrong,
        "quiz_tests_by_concept": quiz_tests_by_concept,
        "outgoing_weak": outgoing_weak,
        "weakest_prereq_by_concept": weakest_prereq_by_concept,
    }


def _taught_in(session, concept_id: str) -> list[dict[str, Any]]:
    rows = (
        session.query(ConceptSectionLink, Section)
        .join(Section, ConceptSectionLink.section_id == Section.id)
        .filter(ConceptSectionLink.concept_id == concept_id)
        .order_by(ConceptSectionLink.rank)
        .all()
    )
    return [
        {
            "section_id": link.section_id,
            "chapter_label": section.chapter_label,
            "title": section.title,
            "rank": link.rank,
            "relevance_md": link.relevance_md,
        }
        for link, section in rows
    ]


def get_skill_map(course_id: str) -> dict[str, Any]:
    """Router-facing entry point for GET .../skills. Course existence is
    checked by the router (same pattern as list_tests) before this is
    called.
    """
    session = get_session()
    try:
        data = build_map(session, course_id)
        return {"nodes": data["nodes"], "edges": data["edges"]}
    finally:
        session.close()


def get_skill_detail(course_id: str, concept_id: str) -> dict[str, Any] | None:
    """Router-facing entry point for GET .../skills/{concept_id}. Returns
    None when the concept doesn't exist in this course (the router turns
    that into a 404); course existence itself is checked by the router.
    """
    session = get_session()
    try:
        data = build_map(session, course_id)
        concept = data["by_id"].get(concept_id)
        if concept is None:
            return None
        node = next(n for n in data["nodes"] if n["id"] == concept_id)

        missed_questions = []
        for test, attempt in data["quiz_tests_by_concept"].get(concept_id, []):
            for i, result in enumerate(attempt.results):
                if result["correct"] is not False:
                    continue
                question = test.questions[i]
                your_answer_idx = result.get("your_answer")
                missed_questions.append(
                    {
                        "question": question["question"],
                        "your_answer": (
                            question["choices"][your_answer_idx]
                            if your_answer_idx is not None
                            else None
                        ),
                        "correct_answer": question["choices"][question["correct_index"]],
                        "source_test_id": test.id,
                        "attempted_at": attempt.created_at,
                    }
                )

        blocked_skill_labels = sorted(
            data["by_id"][to_id].label for to_id in data["outgoing_weak"].get(concept_id, [])
        )

        fix_plan = None
        weakest = data["weakest_prereq_by_concept"].get(concept_id)
        if weakest is not None:
            top_link = (
                session.query(ConceptSectionLink)
                .filter(ConceptSectionLink.concept_id == weakest.id)
                .order_by(ConceptSectionLink.rank)
                .first()
            )
            fix_plan = {
                "prereq_id": weakest.id,
                "prereq_label": weakest.label,
                "section_id": top_link.section_id if top_link is not None else weakest.section_id,
            }

        return {
            "node": node,
            "taught_in": _taught_in(session, concept_id),
            "missed_questions": missed_questions,
            "blocked_skill_labels": blocked_skill_labels,
            "cards_count": data["cards_count"].get(concept_id, 0),
            "quiz_correct": data["quiz_correct"].get(concept_id, 0),
            "quiz_wrong": data["quiz_wrong"].get(concept_id, 0),
            "fix_plan": fix_plan,
        }
    finally:
        session.close()
