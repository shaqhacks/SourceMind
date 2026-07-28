from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _graph(section_id):
    return {
        "concepts": [
            {
                "slug": "tokenization",
                "label": "Tokenization",
                "section_refs": [
                    {"section_id": section_id, "rank": 0, "relevance_md": "Defines tokens."}
                ],
            },
            {"slug": "counting", "label": "Token counting", "section_refs": []},
        ],
        "edges": [{"from_slug": "tokenization", "to_slug": "counting"}],
    }


def test_import_graph_creates_nodes_edges_links(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(section_id))
    assert resp.status_code == 200
    assert resp.json() == {"concept_count": 2, "edge_count": 1, "link_count": 1}


def test_import_is_idempotent_and_preserves_concept_ids(client, ingest_course):
    from conftest import _first_section_id

    from app.db.engine import get_session
    from app.db.models import Concept, ConceptMastery

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    first = client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(section_id))
    assert first.status_code == 200

    session = get_session()
    try:
        concept_ids = {
            c.slug: c.id for c in session.query(Concept).filter_by(course_id=course_id).all()
        }
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=concept_ids["tokenization"],
                learner_key="default",
                points=10,
                correct_count=3,
                wrong_count=1,
            )
        )
        session.commit()
    finally:
        session.close()

    second = client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(section_id))
    assert second.status_code == 200
    assert second.json() == {"concept_count": 2, "edge_count": 1, "link_count": 1}

    session = get_session()
    try:
        concept_ids_after = {
            c.slug: c.id for c in session.query(Concept).filter_by(course_id=course_id).all()
        }
        assert concept_ids_after == concept_ids

        mastery = session.get(
            ConceptMastery, (course_id, concept_ids["tokenization"], "default")
        )
        assert mastery is not None
        assert mastery.points == 10
    finally:
        session.close()


def test_import_rejects_cycle_with_422(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    payload = {
        "concepts": [
            {"slug": "a", "label": "A", "section_refs": []},
            {"slug": "b", "label": "B", "section_refs": []},
        ],
        "edges": [
            {"from_slug": "a", "to_slug": "b"},
            {"from_slug": "b", "to_slug": "a"},
        ],
    }
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 422


def test_import_rejects_duplicate_slug_with_422(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    payload = {
        "concepts": [
            {"slug": "a", "label": "A", "section_refs": []},
            {"slug": "a", "label": "A again", "section_refs": []},
        ],
        "edges": [],
    }
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 422


def test_import_rejects_edge_referencing_unknown_slug_with_422(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    payload = {
        "concepts": [{"slug": "a", "label": "A", "section_refs": []}],
        "edges": [{"from_slug": "a", "to_slug": "does-not-exist"}],
    }
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 422


def test_import_graph_404_for_missing_course(client):
    payload = {"concepts": [{"slug": "a", "label": "A", "section_refs": []}], "edges": []}
    resp = client.put("/api/courses/does-not-exist/skills/graph", json=payload)
    assert resp.status_code == 404


def test_import_rejects_foreign_section_with_422(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    other_course_id, *_ = ingest_course("with_bookmarks.pdf")
    foreign_section_id = _first_section_id(client, other_course_id)

    resp = client.put(
        f"/api/courses/{course_id}/skills/graph", json=_graph(foreign_section_id)
    )
    assert resp.status_code == 422


def test_import_dedupes_duplicate_edge_pair(client, ingest_course):
    from app.db.engine import get_session
    from app.db.models import ConceptEdge

    course_id, *_ = ingest_course("with_bookmarks.pdf")

    payload = {
        "concepts": [
            {"slug": "a", "label": "A", "section_refs": []},
            {"slug": "b", "label": "B", "section_refs": []},
        ],
        "edges": [
            {"from_slug": "a", "to_slug": "b"},
            {"from_slug": "a", "to_slug": "b"},
        ],
    }
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"concept_count": 2, "edge_count": 1, "link_count": 0}

    session = get_session()
    try:
        assert session.query(ConceptEdge).filter_by(course_id=course_id).count() == 1
    finally:
        session.close()


def test_import_dedupes_duplicate_section_ref(client, ingest_course):
    from conftest import _first_section_id

    from app.db.engine import get_session
    from app.db.models import ConceptSectionLink

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    payload = {
        "concepts": [
            {
                "slug": "tokenization",
                "label": "Tokenization",
                "section_refs": [
                    {"section_id": section_id, "rank": 0, "relevance_md": "First."},
                    {"section_id": section_id, "rank": 1, "relevance_md": "Second."},
                ],
            },
        ],
        "edges": [],
    }
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"concept_count": 1, "edge_count": 0, "link_count": 1}

    session = get_session()
    try:
        links = session.query(ConceptSectionLink).filter_by(course_id=course_id).all()
        assert len(links) == 1
        assert links[0].relevance_md == "First."
    finally:
        session.close()


def test_import_then_read_roundtrip(client, ingest_course):
    """PUT .../skills/graph followed by the two GET read endpoints — the map
    must reflect exactly the imported concepts/edges (by slug, since ids are
    server-generated) and the detail endpoint must surface the imported
    section link with its relevance_md."""
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    put_resp = client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(section_id))
    assert put_resp.status_code == 200

    map_resp = client.get(f"/api/courses/{course_id}/skills")
    assert map_resp.status_code == 200
    body = map_resp.json()

    nodes_by_slug = {n["slug"]: n for n in body["nodes"]}
    assert set(nodes_by_slug) == {"tokenization", "counting"}
    assert nodes_by_slug["tokenization"]["level"] == 1
    assert nodes_by_slug["counting"]["level"] == 2

    tokenization_id = nodes_by_slug["tokenization"]["id"]
    counting_id = nodes_by_slug["counting"]["id"]

    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert edge["from_id"] == tokenization_id
    assert edge["to_id"] == counting_id

    detail_resp = client.get(f"/api/courses/{course_id}/skills/{tokenization_id}")
    assert detail_resp.status_code == 200
    taught_in = detail_resp.json()["taught_in"]
    assert any(
        t["section_id"] == section_id and t["relevance_md"] == "Defines tokens."
        for t in taught_in
    )


# --- Read endpoints: map + detail ---------------------------------------


def test_skill_map_computes_mastery_status_levels_and_weak_edge(client, ingest_course):
    from app.db.engine import get_session
    from app.db.models import Concept, ConceptEdge, ConceptMastery

    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        concept_a = Concept(course_id=course_id, slug="tokenization", label="Tokenization")
        concept_b = Concept(course_id=course_id, slug="counting", label="Token counting")
        session.add_all([concept_a, concept_b])
        session.flush()

        session.add(
            ConceptEdge(
                course_id=course_id, from_concept_id=concept_a.id, to_concept_id=concept_b.id
            )
        )
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=concept_a.id,
                learner_key="default",
                correct_count=1,
                wrong_count=9,
            )
        )
        session.commit()
        a_id, b_id = concept_a.id, concept_b.id
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course_id}/skills")
    assert resp.status_code == 200
    body = resp.json()
    nodes_by_id = {n["id"]: n for n in body["nodes"]}

    node_a = nodes_by_id[a_id]
    assert node_a["mastery"] == 10
    assert node_a["status"] == "struggling"
    assert node_a["level"] == 1
    assert node_a["blocked"] is False

    node_b = nodes_by_id[b_id]
    assert node_b["mastery"] == 0
    assert node_b["status"] == "locked"
    assert node_b["blocked"] is True
    assert node_b["level"] == 2
    assert node_b["unlock_note"] == "Unlocks at 60 mastery of Tokenization"

    edge = next(e for e in body["edges"] if e["from_id"] == a_id and e["to_id"] == b_id)
    assert edge["kind"] == "weak"


def test_skill_map_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/skills")
    assert resp.status_code == 404


def test_skill_detail_assembles_taught_in_missed_questions_cards_and_fix_plan(
    client, ingest_course
):
    from app.db.engine import get_session
    from app.db.models import (
        Card,
        Concept,
        ConceptEdge,
        ConceptMastery,
        ConceptSectionLink,
        ReviewState,
        Test,
        TestAttempt,
    )

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    s0, s1 = sections[0]["id"], sections[1]["id"]

    session = get_session()
    try:
        concept_c = Concept(course_id=course_id, slug="counting", label="Token counting")
        concept_d = Concept(course_id=course_id, slug="cost", label="Cost estimation")
        session.add_all([concept_c, concept_d])
        session.flush()

        session.add(
            ConceptEdge(
                course_id=course_id, from_concept_id=concept_c.id, to_concept_id=concept_d.id
            )
        )

        # taught_in: two links, rank 0 (s1) must sort before rank 1 (s0).
        session.add(
            ConceptSectionLink(
                course_id=course_id,
                concept_id=concept_c.id,
                section_id=s1,
                rank=0,
                relevance_md="First appearance.",
            )
        )
        session.add(
            ConceptSectionLink(
                course_id=course_id,
                concept_id=concept_c.id,
                section_id=s0,
                rank=1,
                relevance_md="Second appearance.",
            )
        )

        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=concept_c.id,
                learner_key="default",
                correct_count=1,
                wrong_count=9,
            )
        )

        card = Card(
            id="card-counting-1",
            course_id=course_id,
            section_id=s1,
            front_md="Q",
            back_md="A",
            position=0,
        )
        session.add(card)
        session.flush()
        session.add(
            ReviewState(
                card_id=card.id,
                course_id=course_id,
                due_at=datetime.now(timezone.utc),
                interval_days=1.0,
                ease=2.5,
                reps=1,
                lapses=0,
                last_grade=1,
            )
        )

        test = Test(
            course_id=course_id,
            section_id=s0,
            questions=[
                {
                    "question": "What is a token?",
                    "choices": ["Word", "Byte-pair unit", "Sentence", "Page"],
                    "correct_index": 1,
                    "explanation": "x",
                },
                {
                    "question": "Which unit does GPT-2 use?",
                    "choices": ["Character", "Byte-pair token", "Whole word", "Sentence"],
                    "correct_index": 1,
                    "explanation": "x",
                },
            ],
        )
        session.add(test)
        session.flush()
        attempt = TestAttempt(
            test_id=test.id,
            course_id=course_id,
            answers=[1, 0],
            results=[
                {"correct": True, "correct_index": 1, "explanation": "x", "your_answer": 1},
                {"correct": False, "correct_index": 1, "explanation": "x", "your_answer": 0},
            ],
            score=0.5,
        )
        session.add(attempt)
        session.commit()
        c_id, d_id, test_id = concept_c.id, concept_d.id, test.id
    finally:
        session.close()

    detail_c = client.get(f"/api/courses/{course_id}/skills/{c_id}").json()

    assert detail_c["node"]["id"] == c_id
    assert detail_c["node"]["mastery"] == 28
    assert detail_c["node"]["status"] == "struggling"

    assert detail_c["taught_in"] == [
        {
            "section_id": s1,
            "chapter_label": sections[1]["chapter_label"],
            "title": sections[1]["title"],
            "rank": 0,
            "relevance_md": "First appearance.",
        },
        {
            "section_id": s0,
            "chapter_label": sections[0]["chapter_label"],
            "title": sections[0]["title"],
            "rank": 1,
            "relevance_md": "Second appearance.",
        },
    ]

    assert len(detail_c["missed_questions"]) == 1
    missed = detail_c["missed_questions"][0]
    assert missed["question"] == "Which unit does GPT-2 use?"
    assert missed["your_answer"] == "Character"
    assert missed["correct_answer"] == "Byte-pair token"
    assert missed["source_test_id"] == test_id
    assert missed["attempted_at"] is not None

    assert detail_c["cards_count"] == 1
    assert detail_c["quiz_correct"] == 1
    assert detail_c["quiz_wrong"] == 1
    assert detail_c["blocked_skill_labels"] == ["Cost estimation"]
    assert detail_c["fix_plan"] is None

    detail_d = client.get(f"/api/courses/{course_id}/skills/{d_id}").json()
    assert detail_d["node"]["mastery"] == 0
    assert detail_d["node"]["status"] == "locked"
    assert detail_d["node"]["blocked"] is True
    assert detail_d["node"]["unlock_note"] == "Unlocks at 60 mastery of Token counting"
    assert detail_d["taught_in"] == []
    assert detail_d["missed_questions"] == []
    assert detail_d["cards_count"] == 0
    assert detail_d["quiz_correct"] == 0
    assert detail_d["quiz_wrong"] == 0
    assert detail_d["blocked_skill_labels"] == []
    assert detail_d["fix_plan"] == {
        "prereq_id": c_id,
        "prereq_label": "Token counting",
        "section_id": s1,
    }


def test_skill_detail_404_for_foreign_concept_id(client, ingest_course):
    from app.db.engine import get_session
    from app.db.models import Concept

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    other_course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        foreign = Concept(course_id=other_course_id, slug="foreign", label="Foreign")
        session.add(foreign)
        session.commit()
        foreign_id = foreign.id
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course_id}/skills/{foreign_id}")
    assert resp.status_code == 404

    resp = client.get(f"/api/courses/{course_id}/skills/does-not-exist")
    assert resp.status_code == 404


def test_blocked_is_independent_of_status(client, ingest_course):
    """A concept can already have its own signal (mastery in the
    struggling/growing/solid range) and STILL be `blocked` if one of its
    prerequisites is weak — `blocked` is not just a synonym for status
    "locked". A prereq that's solid must NOT mark its dependent blocked.
    """
    from app.db.engine import get_session
    from app.db.models import Concept, ConceptEdge, ConceptMastery

    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        weak_prereq = Concept(course_id=course_id, slug="weak-prereq", label="Weak Prereq")
        solid_prereq = Concept(course_id=course_id, slug="solid-prereq", label="Solid Prereq")
        struggling = Concept(course_id=course_id, slug="struggling", label="Struggling Skill")
        solid_dependent = Concept(
            course_id=course_id, slug="solid-dependent", label="Solid Dependent"
        )
        session.add_all([weak_prereq, solid_prereq, struggling, solid_dependent])
        session.flush()

        session.add(
            ConceptEdge(
                course_id=course_id,
                from_concept_id=weak_prereq.id,
                to_concept_id=struggling.id,
            )
        )
        session.add(
            ConceptEdge(
                course_id=course_id,
                from_concept_id=solid_prereq.id,
                to_concept_id=solid_dependent.id,
            )
        )

        # weak_prereq: mastery 10 (well below WEAK_PREREQ_BELOW=60).
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=weak_prereq.id,
                learner_key="default",
                correct_count=1,
                wrong_count=9,
            )
        )
        # solid_prereq: mastery 90 (above WEAK_PREREQ_BELOW).
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=solid_prereq.id,
                learner_key="default",
                correct_count=9,
                wrong_count=1,
            )
        )
        # struggling: HAS its own signal (mastery 30, struggling range)
        # despite the weak prereq — must not be "locked".
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=struggling.id,
                learner_key="default",
                correct_count=3,
                wrong_count=7,
            )
        )
        # solid_dependent: signal present, solid mastery, prereq solid.
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=solid_dependent.id,
                learner_key="default",
                correct_count=9,
                wrong_count=1,
            )
        )
        session.commit()
        struggling_id, solid_dependent_id = struggling.id, solid_dependent.id
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course_id}/skills")
    assert resp.status_code == 200
    nodes_by_id = {n["id"]: n for n in resp.json()["nodes"]}

    node = nodes_by_id[struggling_id]
    assert node["mastery"] == 30
    assert node["status"] == "struggling"
    assert node["blocked"] is True
    # Already has signal -> not "locked" -> no unlock note, even though blocked.
    assert node["unlock_note"] is None

    solid_node = nodes_by_id[solid_dependent_id]
    assert solid_node["status"] == "solid"
    assert solid_node["blocked"] is False


def test_quiz_signal_reaches_concept_via_section_id_pointer_without_links(client, ingest_course):
    """A concept created by the (separate) inline-practice feature carries
    only Concept.section_id, no ConceptSectionLink rows. Quiz-scope
    attribution must still reach it (harmonized with the SRS/cards_count
    section pool: links ∪ Concept.section_id) — taught_in, which is
    links-only, correctly stays empty for it.
    """
    from app.db.engine import get_session
    from app.db.models import Concept, Test, TestAttempt

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    s0 = sections[0]["id"]

    session = get_session()
    try:
        concept = Concept(
            course_id=course_id, slug="practice-only", label="Practice Only", section_id=s0
        )
        session.add(concept)
        session.flush()

        test = Test(
            course_id=course_id,
            section_id=s0,
            questions=[
                {"question": "Q1?", "choices": ["A", "B"], "correct_index": 0, "explanation": ""}
            ],
        )
        session.add(test)
        session.flush()
        session.add(
            TestAttempt(
                test_id=test.id,
                course_id=course_id,
                answers=[0],
                results=[
                    {"correct": True, "correct_index": 0, "explanation": "", "your_answer": 0}
                ],
                score=1.0,
            )
        )
        session.commit()
        concept_id = concept.id
    finally:
        session.close()

    detail = client.get(f"/api/courses/{course_id}/skills/{concept_id}").json()
    assert detail["quiz_correct"] == 1
    assert detail["quiz_wrong"] == 0
    assert detail["taught_in"] == []


def test_skill_detail_survives_out_of_range_your_answer_index(client, ingest_course):
    """submit_test never validates a submitted answer index against
    len(choices) (tests_service.py accepts answers like [99] unchecked), so
    a stored TestAttempt.results row can carry an out-of-range your_answer.
    The detail endpoint must degrade that to your_answer=None, not crash
    with an uncaught IndexError on every request whose quiz scope includes
    the bad row.
    """
    from app.db.engine import get_session
    from app.db.models import Concept, ConceptSectionLink, Test, TestAttempt

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    s0 = sections[0]["id"]

    session = get_session()
    try:
        concept = Concept(course_id=course_id, slug="oob-answer", label="Out Of Range")
        session.add(concept)
        session.flush()
        session.add(
            ConceptSectionLink(course_id=course_id, concept_id=concept.id, section_id=s0, rank=0)
        )

        test = Test(
            course_id=course_id,
            section_id=s0,
            questions=[
                {
                    "question": "Which is correct?",
                    "choices": ["A", "B"],
                    "correct_index": 0,
                    "explanation": "",
                }
            ],
        )
        session.add(test)
        session.flush()
        session.add(
            TestAttempt(
                test_id=test.id,
                course_id=course_id,
                answers=[99],
                results=[
                    {"correct": False, "correct_index": 0, "explanation": "", "your_answer": 99}
                ],
                score=0.0,
            )
        )
        session.commit()
        concept_id = concept.id
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course_id}/skills/{concept_id}")
    assert resp.status_code == 200
    missed = resp.json()["missed_questions"]
    assert len(missed) == 1
    assert missed[0]["your_answer"] is None
    assert missed[0]["correct_answer"] == "A"


def test_skill_detail_404_for_missing_course(client):
    """The detail endpoint's OWN course-404 branch (distinct from its
    concept-404 branch below it) — existing tests only vary concept_id
    against a real course_id."""
    resp = client.get("/api/courses/does-not-exist/skills/some-concept")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "course not found"


def test_weakest_prereq_picks_lowest_mastery_among_multiple_weak_edges(client, ingest_course):
    """A concept with TWO incoming weak-prereq edges (both < WEAK_PREREQ_BELOW)
    must select the LOWER-mastery one for fix_plan/unlock_note, not just
    whichever edge happens to be iterated first."""
    from app.db.engine import get_session
    from app.db.models import Concept, ConceptEdge, ConceptMastery

    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        weaker = Concept(course_id=course_id, slug="weaker", label="Weaker Prereq")
        stronger_weak = Concept(
            course_id=course_id, slug="stronger-weak", label="Stronger Weak Prereq"
        )
        dependent = Concept(course_id=course_id, slug="multi-dependent", label="Multi Dependent")
        session.add_all([weaker, stronger_weak, dependent])
        session.flush()

        session.add(
            ConceptEdge(
                course_id=course_id, from_concept_id=weaker.id, to_concept_id=dependent.id
            )
        )
        session.add(
            ConceptEdge(
                course_id=course_id, from_concept_id=stronger_weak.id, to_concept_id=dependent.id
            )
        )

        # weaker: mastery 10 (well below WEAK_PREREQ_BELOW=60).
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=weaker.id,
                learner_key="default",
                correct_count=1,
                wrong_count=9,
            )
        )
        # stronger_weak: mastery 50 -- still weak (< 60) but higher than weaker's 10.
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=stronger_weak.id,
                learner_key="default",
                correct_count=5,
                wrong_count=5,
            )
        )
        session.commit()
        weaker_id, dependent_id = weaker.id, dependent.id
    finally:
        session.close()

    detail = client.get(f"/api/courses/{course_id}/skills/{dependent_id}").json()
    assert detail["node"]["blocked"] is True
    assert detail["node"]["unlock_note"] == "Unlocks at 60 mastery of Weaker Prereq"
    assert detail["fix_plan"]["prereq_id"] == weaker_id
    assert detail["fix_plan"]["prereq_label"] == "Weaker Prereq"


def test_weakest_prereq_tie_break_uses_lower_concept_id(client, ingest_course):
    """When two weak prereqs have IDENTICAL mastery, the min(key=(mastery,
    id)) tie-break must pick the lexicographically lower concept id --
    resolved against the actual server-generated ids, not an assumption
    about insertion order (ids are random uuid4, not sortable-by-creation)."""
    from app.db.engine import get_session
    from app.db.models import Concept, ConceptEdge, ConceptMastery

    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        prereq_x = Concept(course_id=course_id, slug="prereq-x", label="Prereq X")
        prereq_y = Concept(course_id=course_id, slug="prereq-y", label="Prereq Y")
        dependent = Concept(course_id=course_id, slug="tie-dependent", label="Tie Dependent")
        session.add_all([prereq_x, prereq_y, dependent])
        session.flush()

        session.add(
            ConceptEdge(
                course_id=course_id, from_concept_id=prereq_x.id, to_concept_id=dependent.id
            )
        )
        session.add(
            ConceptEdge(
                course_id=course_id, from_concept_id=prereq_y.id, to_concept_id=dependent.id
            )
        )

        # Identical mastery for both prereqs -- forces the id tie-break.
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=prereq_x.id,
                learner_key="default",
                correct_count=1,
                wrong_count=9,
            )
        )
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=prereq_y.id,
                learner_key="default",
                correct_count=1,
                wrong_count=9,
            )
        )
        session.commit()
        prereq_x_id, prereq_y_id, dependent_id = prereq_x.id, prereq_y.id, dependent.id
    finally:
        session.close()

    label_by_id = {prereq_x_id: "Prereq X", prereq_y_id: "Prereq Y"}
    expected_winner_id = min(prereq_x_id, prereq_y_id)
    expected_winner_label = label_by_id[expected_winner_id]

    detail = client.get(f"/api/courses/{course_id}/skills/{dependent_id}").json()
    assert detail["fix_plan"]["prereq_id"] == expected_winner_id
    assert detail["fix_plan"]["prereq_label"] == expected_winner_label
    assert detail["node"]["unlock_note"] == f"Unlocks at 60 mastery of {expected_winner_label}"


def test_quiz_signal_attributes_to_concepts_in_chapter_scope_only(client, ingest_course):
    """A chapter-scoped test (Test.section_id=None, chapter_label set) must
    attribute its results to concepts linked to THAT chapter's sections
    only -- a concept linked to a different chapter's section must see no
    signal at all."""
    from app.db.engine import get_session
    from app.db.models import Concept, ConceptSectionLink, Test, TestAttempt

    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    by_title = {s["title"]: s for s in sections}
    ch1_section_id = by_title["Chapter 1: Foundations"]["id"]
    ch2_section_id = by_title["Chapter 2: Structures"]["id"]

    session = get_session()
    try:
        in_scope = Concept(course_id=course_id, slug="in-scope", label="In Scope")
        out_of_scope = Concept(course_id=course_id, slug="out-of-scope", label="Out Of Scope")
        session.add_all([in_scope, out_of_scope])
        session.flush()
        session.add(
            ConceptSectionLink(
                course_id=course_id, concept_id=in_scope.id, section_id=ch1_section_id, rank=0
            )
        )
        session.add(
            ConceptSectionLink(
                course_id=course_id, concept_id=out_of_scope.id, section_id=ch2_section_id, rank=0
            )
        )

        test = Test(
            course_id=course_id,
            chapter_label="Chapter 1: Foundations",
            section_id=None,
            questions=[
                {"question": "Q1?", "choices": ["A", "B"], "correct_index": 0, "explanation": ""},
                {"question": "Q2?", "choices": ["A", "B"], "correct_index": 0, "explanation": ""},
            ],
        )
        session.add(test)
        session.flush()
        session.add(
            TestAttempt(
                test_id=test.id,
                course_id=course_id,
                answers=[0, 1],
                results=[
                    {"correct": True, "correct_index": 0, "explanation": "", "your_answer": 0},
                    {"correct": False, "correct_index": 0, "explanation": "", "your_answer": 1},
                ],
                score=0.5,
            )
        )
        session.commit()
        in_scope_id, out_of_scope_id = in_scope.id, out_of_scope.id
    finally:
        session.close()

    in_detail = client.get(f"/api/courses/{course_id}/skills/{in_scope_id}").json()
    assert in_detail["quiz_correct"] == 1
    assert in_detail["quiz_wrong"] == 1

    out_detail = client.get(f"/api/courses/{course_id}/skills/{out_of_scope_id}").json()
    assert out_detail["quiz_correct"] == 0
    assert out_detail["quiz_wrong"] == 0


def test_test_scope_section_ids_whole_course_fallback_returns_all_sections():
    """Unit test of _test_scope_section_ids' own contract for a whole-course
    test (section_id AND chapter_label both None): it returns the literal
    all_section_ids list verbatim. Unlike the chapter-scoped branch (which
    filters out kind=='answers' sections), this fallback branch does NOT
    filter anything -- read the function, don't assume symmetry."""
    from app.db.models import Test
    from app.services.skills_service import _test_scope_section_ids

    whole_course_test = Test(course_id="irrelevant", chapter_label=None, section_id=None, questions=[])
    all_section_ids = ["s-answers", "s-content", "s-practice"]

    result = _test_scope_section_ids(
        whole_course_test, sections_by_chapter={}, all_section_ids=all_section_ids
    )
    assert result == all_section_ids


def test_fix_plan_section_falls_back_to_weakest_concept_section_id_pointer(client, ingest_course):
    """The weakest prereq may have ZERO ConceptSectionLink rows (e.g. an
    inline-practice-only concept) but still carry a Concept.section_id
    pointer -- fix_plan.section_id must fall back to that pointer instead
    of staying None."""
    from app.db.engine import get_session
    from app.db.models import Concept, ConceptEdge, ConceptMastery

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    s0 = sections[0]["id"]

    session = get_session()
    try:
        weak_prereq = Concept(
            course_id=course_id, slug="pointer-only-weak", label="Pointer Only Weak", section_id=s0
        )
        dependent = Concept(course_id=course_id, slug="pointer-dependent", label="Pointer Dependent")
        session.add_all([weak_prereq, dependent])
        session.flush()

        session.add(
            ConceptEdge(
                course_id=course_id, from_concept_id=weak_prereq.id, to_concept_id=dependent.id
            )
        )
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=weak_prereq.id,
                learner_key="default",
                correct_count=1,
                wrong_count=9,
            )
        )
        session.commit()
        dependent_id = dependent.id
    finally:
        session.close()

    detail = client.get(f"/api/courses/{course_id}/skills/{dependent_id}").json()
    assert detail["fix_plan"] is not None
    assert detail["fix_plan"]["section_id"] == s0


def test_srs_signal_and_cards_count_reach_concept_via_section_id_pointer_without_links(
    client, ingest_course
):
    """The links ∪ Concept.section_id union (build_map's
    signal_section_ids_by_concept) must feed BOTH cards_count and the SRS
    signal, not just quiz attribution -- a link-less concept with only the
    section_id pointer must see cards_count > 0 and a non-null SRS
    contribution once a reviewed card exists in that section."""
    from app.db.engine import get_session
    from app.db.models import Card, Concept, ReviewState

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    s0 = sections[0]["id"]

    session = get_session()
    try:
        concept = Concept(
            course_id=course_id, slug="pointer-only-srs", label="Pointer Only SRS", section_id=s0
        )
        session.add(concept)
        session.flush()

        card = Card(
            id="card-pointer-only-1",
            course_id=course_id,
            section_id=s0,
            front_md="Q",
            back_md="A",
            position=0,
        )
        session.add(card)
        session.flush()
        session.add(
            ReviewState(
                card_id=card.id,
                course_id=course_id,
                due_at=datetime.now(timezone.utc),
                interval_days=1.0,
                ease=2.5,
                reps=1,
                lapses=0,
                last_grade=4,  # EASY -> srs signal == 1.0 (the only signal present)
            )
        )
        session.commit()
        concept_id = concept.id
    finally:
        session.close()

    detail = client.get(f"/api/courses/{course_id}/skills/{concept_id}").json()
    assert detail["cards_count"] == 1
    # Only signal present is SRS at 1.0, fully renormalized to that one weight.
    assert detail["node"]["mastery"] == 100


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {
                "concepts": [
                    {"slug": f"c{i}", "label": "C", "section_refs": []} for i in range(501)
                ],
                "edges": [],
            },
            id="501-concepts-over-max-length",
        ),
        pytest.param(
            {
                "concepts": [
                    {
                        "slug": "a",
                        "label": "A",
                        "section_refs": [
                            {"section_id": f"s{i}", "rank": 0} for i in range(51)
                        ],
                    }
                ],
                "edges": [],
            },
            id="51-section-refs-over-max-length",
        ),
        pytest.param(
            {"concepts": [{"slug": "", "label": "A", "section_refs": []}], "edges": []},
            id="empty-slug-under-min-length",
        ),
    ],
)
def test_import_graph_bounds_rejected_with_422(client, ingest_course, payload):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 422
