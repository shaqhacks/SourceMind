from __future__ import annotations

from app.db.engine import get_session
from app.db.models import LlmCall


def _llm_call_count() -> int:
    session = get_session()
    try:
        return session.query(LlmCall).count()
    finally:
        session.close()


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


def test_llm_status_check_calls_anthropic_probe_without_metering(client, monkeypatch):
    calls = {"models_list": 0}

    class FakeModels:
        def list(self):
            calls["models_list"] += 1

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-readiness")
    monkeypatch.setattr("app.llm.probe.anthropic.Anthropic", FakeAnthropic)
    calls_before = _llm_call_count()

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["available"] is True
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-sonnet-5"
    assert body["capabilities"] == {"completion": True, "embeddings": False}
    assert body["failure_category"] is None
    assert body["last_checked_at"] is not None
    assert calls["models_list"] == 1
    assert _llm_call_count() == calls_before


def test_llm_status_check_redacts_anthropic_probe_failure(client, monkeypatch):
    secret = "sk-ant-status-secret"

    class FakeModels:
        def list(self):
            raise RuntimeError(f"provider rejected {secret}")

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setattr("app.llm.probe.anthropic.Anthropic", FakeAnthropic)
    calls_before = _llm_call_count()

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    assert secret not in resp.text
    assert "[redacted]" in resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["available"] is False
    assert body["failure_category"] == "provider_error"
    assert _llm_call_count() == calls_before


def test_llm_status_check_calls_ollama_probe_without_metering(client, monkeypatch):
    calls = {"url": None}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_get(url, *, timeout):
        calls["url"] = url
        assert timeout > 0
        return FakeResponse()

    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr("app.llm.probe.httpx.get", fake_get)
    calls_before = _llm_call_count()

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "ollama"
    assert body["model"] == "llama3.2"
    assert body["available"] is True
    assert body["capabilities"] == {"completion": True, "embeddings": True}
    assert body["failure_category"] is None
    assert calls["url"] == "http://127.0.0.1:11434/api/version"
    assert _llm_call_count() == calls_before
