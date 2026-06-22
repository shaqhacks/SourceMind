"""Route tests for the multi-source ingest endpoint (T4 wiring)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from SourceMind.backend import main as api

client = TestClient(api.app)
FIXTURES = Path("backend/tests/fixtures/ingest")


def test_upload_source_accepts_pasted_text():
    resp = client.post(
        "/upload/source",
        json={
            "source_type": "text",
            "title": "Algebra",
            "content": "Chapter 1: Foundations\n1.1 Integers\nIntegers are whole numbers."
            "\f1.2 Fractions\nA fraction is part of a whole.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_type"] == "text"
    assert body["competencies_count"] >= 1
    assert body["rubric_passed"] is True


def test_upload_source_accepts_markdown():
    resp = client.post(
        "/upload/source",
        json={"source_type": "markdown", "title": "Bio", "content": (FIXTURES / "sample.md").read_text()},
    )
    assert resp.status_code == 200
    assert resp.json()["competencies_count"] >= 1


def test_upload_source_accepts_url_html():
    resp = client.post(
        "/upload/source",
        json={"source_type": "url", "title": "Physics", "content": (FIXTURES / "sample.html").read_text()},
    )
    assert resp.status_code == 200


def test_upload_source_accepts_youtube_transcript():
    segments = json.loads((FIXTURES / "youtube_transcript.json").read_text())
    # The endpoint takes a string body; a transcript arrives pre-joined.
    text = " ".join(s["text"] for s in segments)
    resp = client.post("/upload/source", json={"source_type": "youtube", "title": "ML", "content": text})
    assert resp.status_code == 200


def test_upload_source_rejects_garbage_with_422():
    resp = client.post("/upload/source", json={"source_type": "text", "content": "@@@ ### $$$"})
    assert resp.status_code == 422


def test_upload_source_rejects_unknown_type_with_415():
    resp = client.post("/upload/source", json={"source_type": "telepathy", "content": "hello there"})
    assert resp.status_code == 415


def test_upload_source_rejects_oversized_content_with_422():
    # Body cap guards against memory/CPU DoS on the JSON ingest path.
    resp = client.post("/upload/source", json={"source_type": "text", "content": "a" * 2_000_001})
    assert resp.status_code == 422
