from __future__ import annotations

from datetime import datetime, timezone


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
