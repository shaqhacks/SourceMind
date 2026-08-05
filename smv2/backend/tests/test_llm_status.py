from __future__ import annotations

from app.db.engine import get_session
from app.db.models import LlmCall


def test_llm_status_reports_readiness_without_network_call(client):
    resp = client.get("/api/llm/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-sonnet-5"
    assert body["configured"] is False
    assert body["available"] is False
    assert body["capabilities"] == {"completion": False, "embeddings": False}
    assert body["failure_category"] == "missing_credentials"
    assert "ANTHROPIC_API_KEY" in body["remediation"]
    assert body["last_checked_at"] is None


def test_llm_status_check_is_non_metered_and_reports_unverified(client, stub_provider):
    session = get_session()
    try:
        calls_before = session.query(LlmCall).count()
    finally:
        session.close()

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["available"] is False
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-sonnet-5"
    assert body["capabilities"] == {"completion": False, "embeddings": False}
    assert body["failure_category"] == "configured_unverified"
    assert body["last_checked_at"] is not None
    assert stub_provider.call_count == 0

    session = get_session()
    try:
        assert session.query(LlmCall).count() == calls_before
    finally:
        session.close()
