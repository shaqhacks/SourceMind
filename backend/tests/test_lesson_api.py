from pathlib import Path

from fastapi.testclient import TestClient

from SourceMind.backend import main as api
from SourceMind.backend.services.llm_local import GroundingScore, LocalLLMResponse
from SourceMind.backend.services.md_store import Competency, MarkdownSubjectStore, Quote, SubjectDocument


def api_document() -> SubjectDocument:
    return SubjectDocument(
        subject_id="api_lesson",
        competencies=[
            Competency(id="L1", name="Source Recall", level=1, dependencies=[], mastery_percent=0),
            Competency(id="L2", name="Source Transfer", level=2, dependencies=["L1"], mastery_percent=0),
        ],
        quotes=[
            Quote(text="A source-backed idea should be recalled before transfer.", source_ref="p. 1", competency_id="L1", level_id=1),
            Quote(text="Transfer applies a source-backed idea in a new case.", source_ref="p. 2", competency_id="L2", level_id=2),
        ],
    )


def test_subject_detail_reads_existing_lesson_model_without_regeneration(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    document = api.lesson_engine.ensure_lesson_model(api_document())
    store.save(document)
    monkeypatch.setattr(api, "store", store)
    client = TestClient(api.app)

    response = client.get("/subjects/api_lesson")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["subject"]["lesson_model"]) == 2
    assert len(payload["subject"]["retrieval_checks"]) == 6

    loaded = store.load("api_lesson")
    assert len(loaded.lesson_model) == 2
    assert len(loaded.retrieval_checks) == 6

    second = client.get("/subjects/api_lesson")

    assert second.status_code == 200
    assert len(store.load("api_lesson").retrieval_checks) == 6


def test_subject_detail_backfills_existing_lesson_reading(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    document = api.lesson_engine.ensure_lesson_model(api_document())
    document.lesson_model[0].reading = []
    store.save(document)
    monkeypatch.setattr(api, "store", store)
    client = TestClient(api.app)

    response = client.get("/subjects/api_lesson")

    assert response.status_code == 200
    reading = response.json()["subject"]["lesson_model"][0]["reading"]
    assert reading
    assert "This lesson teaches Source Recall" in reading[0]
    assert store.load("api_lesson").lesson_model[0].reading == reading


def test_subject_detail_does_not_generate_lesson_model_on_read(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    store.save(api_document())
    monkeypatch.setattr(api, "store", store)
    client = TestClient(api.app)

    response = client.get("/subjects/api_lesson")

    assert response.status_code == 200
    assert response.json()["subject"]["lesson_model"] == []
    assert store.load("api_lesson").lesson_model == []


def test_lesson_question_endpoint_returns_support_status(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    document = api.lesson_engine.ensure_lesson_model(api_document())
    store.save(document)
    monkeypatch.setattr(api, "store", store)

    class FakeLLM:
        def explain_with_critic(self, question, quotes, mastery_context):
            return LocalLLMResponse(
                response=f"Source-backed answer for: {question}",
                grounding=GroundingScore(grounded_pct=80, inference_pct=15, prediction_pct=5),
                model="fake",
            )

    monkeypatch.setattr(api, "llm_service", FakeLLM())
    client = TestClient(api.app)

    response = client.post(
        "/lessons/question",
        json={"subject_id": "api_lesson", "lesson_id": "LESSON_L1", "question": "What is the source idea?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["support_status"] == "grounded"
    assert payload["quote_scope"] == "lesson_related"
    assert payload["grounding"]["grounded_pct"] == 80
    assert store.load("api_lesson").lesson_state["LESSON_L1"].question_history[0]["support_status"] == "grounded"


def test_lesson_question_falls_back_to_subject_quotes_when_lesson_has_no_direct_quote(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = MarkdownSubjectStore(tmp_path)
    document = SubjectDocument(
        subject_id="sparse_lesson",
        competencies=[
            Competency(id="L1_MISSING", name="Missing Evidence", level=1, dependencies=[], mastery_percent=0),
            Competency(id="L1_SOURCE", name="Available Evidence", level=1, dependencies=[], mastery_percent=0),
        ],
        quotes=[
            Quote(
                text="Available source evidence can still anchor a cautious answer.",
                source_ref="p. 1",
                competency_id="L1_SOURCE",
                level_id=1,
            )
        ],
    )
    api.lesson_engine.ensure_lesson_model(document)
    store.save(document)
    monkeypatch.setattr(api, "store", store)

    captured = {}

    class FakeLLM:
        def explain_with_critic(self, question, quotes, mastery_context):
            captured["quotes"] = quotes
            captured["mastery_context"] = mastery_context
            return LocalLLMResponse(
                response="Cautious source-backed answer.",
                grounding=GroundingScore(grounded_pct=55, inference_pct=35, prediction_pct=10),
                model="fake",
            )

    monkeypatch.setattr(api, "llm_service", FakeLLM())
    client = TestClient(api.app)

    response = client.post(
        "/lessons/question",
        json={
            "subject_id": "sparse_lesson",
            "lesson_id": "LESSON_L1_MISSING",
            "question": "What should I review?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["support_status"] == "inferred"
    assert payload["quote_scope"] == "subject_fallback"
    assert captured["quotes"][0].competency_id == "L1_SOURCE"
    assert captured["mastery_context"]["quote_scope"] == "subject_fallback"


def test_retrieval_check_endpoint_updates_mastery_and_spacing(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    document = api.lesson_engine.ensure_lesson_model(api_document())
    store.save(document)
    monkeypatch.setattr(api, "store", store)
    client = TestClient(api.app)

    response = client.post(
        "/lessons/evaluate-check",
        json={
            "subject_id": "api_lesson",
            "lesson_id": "LESSON_L1",
            "check_id": "RC_L1_1",
            "correct": True,
            "confidence": 5,
            "answer": "A source-backed idea should be recalled before transfer.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluation"]["mastery_percent"] > 0
    assert payload["retrieval_check"]["confidence_history"] == [5]
    assert store.load("api_lesson").lesson_state["LESSON_L1"].completed_check_ids == ["RC_L1_1"]


def test_retrieval_check_endpoint_rejects_check_from_another_lesson(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    document = api.lesson_engine.ensure_lesson_model(api_document())
    store.save(document)
    monkeypatch.setattr(api, "store", store)
    client = TestClient(api.app)

    response = client.post(
        "/lessons/evaluate-check",
        json={
            "subject_id": "api_lesson",
            "lesson_id": "LESSON_L1",
            "check_id": "RC_L2_1",
            "correct": True,
            "confidence": 5,
            "answer": "Transfer applies a source-backed idea in a new case.",
        },
    )

    assert response.status_code == 422
    assert store.load("api_lesson").lesson_state["LESSON_L1"].completed_check_ids == []


def test_cors_origins_include_configured_dev_port(monkeypatch) -> None:
    monkeypatch.setenv("SOURCEMIND_CORS_ORIGINS", "http://127.0.0.1:3001,http://localhost:3001")

    origins = api._cors_origins()

    assert "http://127.0.0.1:3001" in origins
    assert "http://localhost:3001" in origins
    assert "http://127.0.0.1:3000" in origins
