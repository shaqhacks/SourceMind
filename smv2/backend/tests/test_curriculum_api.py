from __future__ import annotations

import json

from app.db.engine import get_session
from app.db.models import CurriculumVersion, Job
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult


def _extraction_response(section_id: str, chapter_label: str | None) -> str:
    return json.dumps(
        {
            "concepts": [
                {
                    "stable_key": "foundations",
                    "label": "Foundations",
                    "description_md": "Understand the chapter foundations.",
                    "aliases": ["basics"],
                    "chapter_label": chapter_label,
                    "sources": [
                        {
                            "section_id": section_id,
                            "source_ref": "Foundations source",
                            "excerpt_md": "Foundational source material.",
                        }
                    ],
                    "confidence": 0.9,
                    "rationale_md": "Defined in the source.",
                }
            ],
            "claims": [
                {
                    "stable_key": "explain-foundations",
                    "concept_key": "foundations",
                    "statement": "Explain the foundational idea.",
                    "success_criteria_md": "Provides an accurate explanation.",
                    "aliases": [],
                    "cognitive_demand": "understand",
                    "sources": [
                        {
                            "section_id": section_id,
                            "source_ref": "Foundations exercise",
                            "excerpt_md": "Explain the foundational idea.",
                        }
                    ],
                    "confidence": 0.85,
                    "rationale_md": "The exercise makes the performance observable.",
                }
            ],
            "relations": [],
        }
    )


def _completion(text: str) -> CompletionResult:
    return CompletionResult(text=text, input_tokens=10, output_tokens=20, model="stub-model")


# headings_no_bookmarks.pdf yields 6 chapter chunks (Chapter 1..5 plus a
# trailing "Answers" section grouped with Chapter 1's label), so a full
# extraction is 6 chunk calls + 1 cross-chapter linking call.
_EMPTY_CURRICULUM = json.dumps({"concepts": [], "claims": [], "relations": []})
_EMPTY_LINK = json.dumps({"relations": []})


def test_curriculum_extraction_job_is_idempotent_reviewable_and_publishable(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    section = next(item for item in sections if item["chapter_label"] is not None)
    # The first chunk (the chapter containing `section`) returns the real
    # curriculum; the remaining 5 chunks are empty, and the cross-chapter
    # linking pass returns no extra edges.
    stub_provider.responses = [
        _completion(_extraction_response(section["id"], section["chapter_label"])),
        *[_completion(_EMPTY_CURRICULUM) for _ in range(5)],
        _completion(_EMPTY_LINK),
    ]

    first = client.post(f"/api/courses/{course_id}/curriculum/extract")
    second = client.post(f"/api/courses/{course_id}/curriculum/extract")

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()
    assert run_due_jobs_once() is True
    job = client.get(f"/api/jobs/{first.json()['job_id']}").json()
    assert job["status"] == "succeeded", job["error"]

    draft = client.get(f"/api/courses/{course_id}/curriculum?view=draft")
    assert draft.status_code == 200
    concept = draft.json()["concepts"][0]
    claim = draft.json()["claims"][0]
    assert claim["concept_id"] == concept["id"]
    assert draft.json()["sources"][0]["section_id"] == section["id"]

    edited = client.patch(
        f"/api/curriculum/{draft.json()['id']}/concepts/{concept['id']}",
        json={
            "label": "Foundational reasoning",
            "description_md": "A reviewed description.",
            "aliases": ["basics"],
            "chapter_label": section["chapter_label"],
        },
    )
    assert edited.status_code == 200
    alignment = client.post(
        f"/api/curriculum/{draft.json()['id']}/standards",
        json={
            "concept_id": concept["id"],
            "external_ref": "CCSS.TEST.1",
            "confidence": 0.8,
            "rationale_md": "Reviewed alignment.",
        },
    )
    assert alignment.status_code == 200
    published = client.post(f"/api/curriculum/{draft.json()['id']}/publish")
    assert published.status_code == 200
    current = client.get(f"/api/courses/{course_id}/curriculum")
    assert current.status_code == 200
    assert current.json()["is_current"] is True
    assert current.json()["concepts"][0]["label"] == "Foundational reasoning"

    immutable_edit = client.patch(
        f"/api/curriculum/{draft.json()['id']}/concepts/{concept['id']}",
        json={
            "label": "Should fail",
            "description_md": "Published versions are immutable.",
            "aliases": [],
            "chapter_label": None,
        },
    )
    assert immutable_edit.status_code == 409


def test_curriculum_extraction_empty_result_fails_instead_of_succeeding(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    # Every chunk returns an empty curriculum — the all-empty guard fails the
    # job before the cross-chapter linking pass ever runs.
    stub_provider.responses = [_completion(_EMPTY_CURRICULUM) for _ in range(6)]

    resp = client.post(f"/api/courses/{course_id}/curriculum/extract")
    assert resp.status_code == 202
    assert run_due_jobs_once() is True
    job = client.get(f"/api/jobs/{resp.json()['job_id']}").json()
    assert job["status"] == "failed", job["error"]
    assert job["error_detail"]["code"] == "invalid_model_output"

    status = client.get(f"/api/courses/{course_id}/skills/status").json()
    assert status["phase"] == "failed"
    assert status["error_code"] == "invalid_model_output"
    assert status["error"] is not None


def test_regeneration_replaces_draft_concepts_not_appends(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    section = next(item for item in sections if item["chapter_label"] is not None)

    def concept_response(stable_key: str, label: str) -> str:
        return json.dumps(
            {
                "concepts": [
                    {
                        "stable_key": stable_key,
                        "label": label,
                        "description_md": "desc",
                        "aliases": [],
                        "chapter_label": section["chapter_label"],
                        "sources": [
                            {
                                "section_id": section["id"],
                                "source_ref": "src",
                                "excerpt_md": "excerpt",
                            }
                        ],
                        "confidence": 0.9,
                        "rationale_md": "rationale",
                    }
                ],
                "claims": [],
                "relations": [],
            }
        )

    stub_provider.responses = [
        _completion(concept_response("alpha", "Alpha")),
        *[_completion(_EMPTY_CURRICULUM) for _ in range(5)],
        _completion(_EMPTY_LINK),
    ]
    client.post(f"/api/courses/{course_id}/curriculum/extract")
    assert run_due_jobs_once() is True

    stub_provider.responses = [
        _completion(concept_response("beta", "Beta")),
        *[_completion(_EMPTY_CURRICULUM) for _ in range(5)],
        _completion(_EMPTY_LINK),
    ]
    client.post(f"/api/courses/{course_id}/curriculum/extract")
    assert run_due_jobs_once() is True

    draft = client.get(f"/api/courses/{course_id}/curriculum?view=draft").json()
    assert [c["label"] for c in draft["concepts"]] == ["Beta"]


def test_curriculum_extraction_locked_once_learning_started(client, ingest_course):
    from app.db.models import Test, TestAttempt
    from app.services import learner_context

    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")

    session = get_session()
    try:
        profile = learner_context.ensure_course_learning_profile(
            session, learner_context.LEGACY_LOCAL_LEARNER_ID, course_id
        )
        test = Test(course_id=course_id, questions=[])
        session.add(test)
        session.flush()
        session.add(
            TestAttempt(
                course_learning_profile_id=profile.id,
                test_id=test.id,
                course_id=course_id,
            )
        )
        session.commit()
    finally:
        session.close()

    resp = client.post(f"/api/courses/{course_id}/curriculum/extract")
    assert resp.status_code == 409
    assert "locked" in resp.json()["detail"]

    status = client.get(f"/api/courses/{course_id}/skills/status").json()
    assert status["locked"] is True


def test_curriculum_extraction_unconfigured_provider_fails_before_job_creation(
    client, ingest_course
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")

    resp = client.post(f"/api/courses/{course_id}/curriculum/extract")

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["failure_category"] == "missing_credentials"
    assert "ANTHROPIC_API_KEY" in body["detail"]["remediation"]

    session = get_session()
    try:
        assert session.query(Job).filter(Job.type == "concept_extraction").count() == 0
        assert session.query(CurriculumVersion).filter_by(course_id=course_id).count() == 0
    finally:
        session.close()


def test_curriculum_endpoints_return_404_for_missing_course_or_version(client):
    assert client.post("/api/courses/missing/curriculum/extract").status_code == 404
    assert client.get("/api/courses/missing/curriculum").status_code == 404
    assert client.post("/api/curriculum/missing/publish").status_code == 404
