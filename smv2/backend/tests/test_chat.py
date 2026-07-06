from __future__ import annotations

import httpx

from app.db.engine import get_session
from app.db.models import ChatTurn, Chunk
from app.llm.limiter import LLMBusyError
from app.llm.provider import PROVIDER_NOT_CONFIGURED_MESSAGE, CompletionResult, ProviderNotConfiguredError


def test_send_chat_happy_path_with_citations(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text="The answer is X [1]. See also [2].", input_tokens=10, output_tokens=10, model="stub-model")
    ]

    resp = client.post(f"/api/courses/{course_id}/chat", json={"message": "What is X?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply_md"] == "The answer is X [1]. See also [2]."
    assert len(body["citations"]) == 2
    ns = {c["n"] for c in body["citations"]}
    assert ns == {1, 2}
    for c in body["citations"]:
        assert "section_id" in c
        assert "source_ref" in c


def test_send_chat_ignores_out_of_range_citations(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text="Answer [1] and also [999].", input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(f"/api/courses/{course_id}/chat", json={"message": "question"})
    body = resp.json()
    ns = {c["n"] for c in body["citations"]}
    assert 999 not in ns


def test_send_chat_persists_both_turns(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text="Reply [1].", input_tokens=1, output_tokens=1, model="stub-model")
    ]

    client.post(f"/api/courses/{course_id}/chat", json={"message": "hello?"})

    session = get_session()
    try:
        turns = session.query(ChatTurn).filter(ChatTurn.course_id == course_id).order_by(ChatTurn.created_at).all()
    finally:
        session.close()

    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].content == "hello?"
    assert turns[1].role == "assistant"
    assert turns[1].content == "Reply [1]."
    assert turns[1].citations is not None


def test_chat_history_returns_persisted_turns(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text="Reply.", input_tokens=1, output_tokens=1, model="stub-model")
    ]
    client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})

    resp = client.get(f"/api/courses/{course_id}/chat")
    assert resp.status_code == 200
    turns = resp.json()
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[1]["role"] == "assistant"


def test_send_chat_404_for_missing_course(client):
    resp = client.post("/api/courses/does-not-exist/chat", json={"message": "hi"})
    assert resp.status_code == 404


def test_chat_history_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/chat")
    assert resp.status_code == 404


def test_send_chat_provider_failure_persists_no_turns(client, ingest_course, stub_provider):
    """A provider error must not leave an orphaned user turn with no
    matching assistant reply — nothing is persisted for this exchange at
    all, so the client can safely retry with the same message. No generic
    500 handler exists (only LLMBusyError has one), so an unhandled
    provider error propagates out of the TestClient call itself.
    """
    import pytest

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    # Not transient (retry_transient won't retry it), so one raise is enough.
    stub_provider.exceptions = [RuntimeError("provider exploded")]

    with pytest.raises(RuntimeError, match="provider exploded"):
        client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})

    session = get_session()
    try:
        turns = session.query(ChatTurn).filter(ChatTurn.course_id == course_id).all()
    finally:
        session.close()
    assert turns == []


def test_chat_history_returns_latest_turns_not_earliest(client, ingest_course, stub_provider):
    """With more turns than the history limit, the response must be the
    MOST RECENT ones (in chronological order), not frozen on the earliest
    ones forever.
    """
    from app.db.models import utcnow
    from datetime import timedelta

    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        base = utcnow()
        for i in range(60):
            session.add(
                ChatTurn(
                    course_id=course_id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"turn {i}",
                    created_at=base + timedelta(seconds=i),
                )
            )
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course_id}/chat")
    assert resp.status_code == 200
    turns = resp.json()
    assert len(turns) == 50
    # The latest 50 (turns 10..59), in chronological order.
    assert turns[0]["content"] == "turn 10"
    assert turns[-1]["content"] == "turn 59"
    contents = [t["content"] for t in turns]
    assert contents == sorted(contents, key=lambda c: int(c.split()[-1]))


def test_send_chat_llm_busy_maps_to_429(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.exceptions = [LLMBusyError("all slots busy")]

    resp = client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})
    assert resp.status_code == 429


def test_send_chat_provider_timeout_maps_to_504(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    # retry_transient retries a timeout once, so both attempts must time out
    # for the error to actually propagate out of provider.complete().
    stub_provider.exceptions = [httpx.TimeoutException("timed out"), httpx.TimeoutException("timed out again")]

    resp = client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})
    assert resp.status_code == 504


def test_send_chat_provider_not_configured_maps_to_503(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.exceptions = [ProviderNotConfiguredError(PROVIDER_NOT_CONFIGURED_MESSAGE)]

    resp = client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == PROVIDER_NOT_CONFIGURED_MESSAGE


def test_send_chat_triggers_embed_course_job_when_no_embeddings_yet(client, ingest_course, stub_provider):
    from app.db.models import Job

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text="Reply.", input_tokens=1, output_tokens=1, model="stub-model")
    ]

    session = get_session()
    try:
        assert session.query(Chunk).filter(Chunk.course_id == course_id, Chunk.embedding.isnot(None)).first() is None
    finally:
        session.close()

    resp = client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})
    assert resp.status_code == 200  # answers this turn regardless (lexically)

    session = get_session()
    try:
        jobs = session.query(Job).filter(Job.type == "embed_course").all()
        assert len(jobs) == 1
        assert jobs[0].payload["course_id"] == course_id
    finally:
        session.close()


def test_send_chat_does_not_duplicate_embed_course_job_across_turns(client, ingest_course, stub_provider):
    from app.db.models import Job

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text="Reply 1.", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text="Reply 2.", input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})
    client.post(f"/api/courses/{course_id}/chat", json={"message": "hi again"})

    session = get_session()
    try:
        jobs = session.query(Job).filter(Job.type == "embed_course").all()
        assert len(jobs) == 1  # still queued from the first turn -> not re-enqueued
    finally:
        session.close()


def test_send_chat_skips_embed_trigger_when_provider_does_not_support_embeddings(
    client, ingest_course, stub_provider
):
    """A provider with no embeddings API at all (e.g. Anthropic) must not
    get a doomed embed_course job enqueued on every single chat turn
    against a zero-embedding course.
    """
    from app.db.models import Job

    stub_provider.supports_embeddings = False
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text="Reply.", input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})
    assert resp.status_code == 200

    session = get_session()
    try:
        jobs = session.query(Job).filter(Job.type == "embed_course").all()
        assert jobs == []
    finally:
        session.close()


def test_send_chat_includes_prior_turns_as_messages(client, ingest_course, stub_provider):
    """The model used to only ever see the newest message in isolation,
    even though the UI presents a multi-turn conversation. Prior turns must
    now be included as proper role messages before the current one.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text="First reply.", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text="Second reply.", input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    client.post(f"/api/courses/{course_id}/chat", json={"message": "first question"})
    client.post(f"/api/courses/{course_id}/chat", json={"message": "second question"})

    assert stub_provider.call_count == 2
    second_call_messages = stub_provider.received_messages[1]

    assert second_call_messages[0] == {"role": "user", "content": "first question"}
    assert second_call_messages[1] == {"role": "assistant", "content": "First reply."}
    assert second_call_messages[-1]["role"] == "user"
    assert "second question" in second_call_messages[-1]["content"]

    # The FIRST call must NOT have had any history prepended (there was none yet).
    first_call_messages = stub_provider.received_messages[0]
    assert len(first_call_messages) == 1
    assert "first question" in first_call_messages[0]["content"]


def test_send_chat_history_window_respects_chat_history_turns_config(
    client, ingest_course, stub_provider, monkeypatch
):
    monkeypatch.setenv("SMV2_CHAT_HISTORY_TURNS", "0")

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text="First reply.", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text="Second reply.", input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    client.post(f"/api/courses/{course_id}/chat", json={"message": "first question"})
    client.post(f"/api/courses/{course_id}/chat", json={"message": "second question"})

    # With history turns disabled, the second call must be JUST the current
    # question — no prior exchange prepended.
    second_call_messages = stub_provider.received_messages[1]
    assert len(second_call_messages) == 1
    assert "second question" in second_call_messages[0]["content"]


def test_send_chat_spend_cap_exceeded_returns_429_with_distinct_detail(
    client, ingest_course, stub_provider, monkeypatch
):
    """Chat's 429 for a blown spend cap must be distinguishable from the
    limiter's 429 ("LLM concurrency limit reached") — a different detail
    message so the client can tell "busy, retry" apart from "out of budget."
    """
    from app.db.models import LlmCall, utcnow

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    monkeypatch.setenv("SMV2_COURSE_SPEND_CAP_USD", "0.0001")

    session = get_session()
    try:
        session.add(
            LlmCall(
                ts=utcnow(),
                purpose="lesson",
                model="claude-sonnet-5",
                input_tokens=1000,
                output_tokens=1000,
                latency_ms=100,
                cost_estimate=0.01,
                status="ok",
                course_id=course_id,
            )
        )
        session.commit()
    finally:
        session.close()

    resp = client.post(f"/api/courses/{course_id}/chat", json={"message": "hi"})
    assert resp.status_code == 429
    assert resp.json()["detail"] == "course spend cap exceeded"
    assert stub_provider.call_count == 0  # never reached the provider
