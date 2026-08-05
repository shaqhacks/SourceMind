from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Job, LlmCall, Section
from conftest import _first_section_id


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
    assert body["failure_category"] == "unreachable"
    assert _llm_call_count() == calls_before


def test_failed_llm_status_check_makes_get_status_unreachable(client, monkeypatch):
    secret = "sk-ant-unreachable-status"

    class FakeModels:
        def list(self):
            raise RuntimeError(f"connection failed for {secret}")

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setattr("app.llm.probe.anthropic.Anthropic", FakeAnthropic)

    check_resp = client.post("/api/llm/status/check")
    status_resp = client.get("/api/llm/status")

    assert check_resp.status_code == 200
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["configured"] is True
    assert body["available"] is False
    assert body["failure_category"] == "unreachable"
    assert secret not in status_resp.text
    assert "[redacted]" in status_resp.text


def test_failed_llm_status_check_blocks_generation_before_job_creation(
    client, ingest_course, monkeypatch
):
    class FakeModels:
        def list(self):
            raise RuntimeError("provider unreachable")

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-unreachable-generation")
    monkeypatch.setattr("app.llm.probe.anthropic.Anthropic", FakeAnthropic)
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    check_resp = client.post("/api/llm/status/check")
    generation_resp = client.post(f"/api/sections/{section_id}/lesson")

    assert check_resp.status_code == 200
    assert generation_resp.status_code == 503
    assert generation_resp.json()["detail"]["failure_category"] == "unreachable"
    session = get_session()
    try:
        assert session.query(Job).filter(Job.type == "generate_lesson").count() == 0
        assert session.get(Section, section_id).lesson_status == "none"
    finally:
        session.close()


def test_successful_llm_status_recheck_supersedes_failed_check(client, monkeypatch):
    calls = {"fail": True}

    class FakeModels:
        def list(self):
            if calls["fail"]:
                raise RuntimeError("provider unreachable")

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-recheck")
    monkeypatch.setattr("app.llm.probe.anthropic.Anthropic", FakeAnthropic)

    failed = client.post("/api/llm/status/check").json()
    calls["fail"] = False
    succeeded = client.post("/api/llm/status/check").json()
    status = client.get("/api/llm/status").json()

    assert failed["available"] is False
    assert succeeded["available"] is True
    assert succeeded["failure_category"] is None
    assert status["available"] is True
    assert status["failure_category"] is None


def test_llm_status_config_identity_change_invalidates_stale_check(client, monkeypatch):
    class FakeModels:
        def list(self):
            raise RuntimeError("provider unreachable")

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-old")
    monkeypatch.setattr("app.llm.probe.anthropic.Anthropic", FakeAnthropic)
    failed = client.post("/api/llm/status/check").json()
    assert failed["available"] is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-new")
    credential_changed = client.get("/api/llm/status").json()
    assert credential_changed["available"] is True
    assert credential_changed["failure_category"] is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-old")
    monkeypatch.setenv("SMV2_LLM_MODEL", "claude-new-model")
    model_changed = client.get("/api/llm/status").json()
    assert model_changed["model"] == "claude-new-model"
    assert model_changed["available"] is True
    assert model_changed["failure_category"] is None

    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    provider_changed = client.get("/api/llm/status").json()
    assert provider_changed["provider"] == "ollama"
    assert provider_changed["available"] is True
    assert provider_changed["capabilities"] == {"completion": True, "embeddings": True}


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
