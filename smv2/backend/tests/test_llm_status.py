from __future__ import annotations

import json
from types import SimpleNamespace

from conftest import _first_section_id

from app.db.engine import get_session
from app.db.models import Job, LlmCall, Section


def _llm_call_count() -> int:
    session = get_session()
    try:
        return session.query(LlmCall).count()
    finally:
        session.close()


class _FakeOllamaResponse:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.is_redirect = False
        self.content = b"{}"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("ollama request failed")

    def json(self):
        return self._payload

    def iter_bytes(self):
        yield json.dumps(self._payload).encode("utf-8")


class _FakeOllamaClient:
    def __init__(self, *, model_capabilities: dict[str, list[str]], calls: list[dict]):
        self._model_capabilities = model_capabilities
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, path: str, *, json: dict):
        name = json["name"]
        self._calls.append({"path": path, "name": name})
        capabilities = self._model_capabilities.get(name)
        if capabilities is None:
            return _FakeOllamaResponse(status_code=404)
        return _FakeOllamaResponse(payload={"capabilities": capabilities})

    def stream(self, method: str, path: str, *, json: dict):
        assert method == "POST"
        return self.post(path, json=json)


def _patch_ollama_probe(monkeypatch, model_capabilities: dict[str, list[str]]) -> list[dict]:
    calls: list[dict] = []

    def fake_client(**kwargs):
        calls.append({"client_kwargs": kwargs})
        return _FakeOllamaClient(model_capabilities=model_capabilities, calls=calls)

    monkeypatch.setattr("app.llm.probe.httpx.Client", fake_client)
    monkeypatch.setattr("app.llm.probe.httpx.get", lambda *args, **kwargs: _FakeOllamaResponse())
    return calls


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


def test_llm_status_check_rejects_unsafe_configured_ollama_url_before_http_client(
    client, monkeypatch
):
    unsafe_urls = [
        "http://8.8.8.8:11434",
        "http://user:pass@localhost:11434",
        "http://169.254.169.254:11434",
        "http://2130706433:11434",
    ]
    created_clients = 0

    def fail_if_client_created(**kwargs):
        nonlocal created_clients
        created_clients += 1
        raise AssertionError("unsafe Ollama URL must not create an HTTP client")

    monkeypatch.setattr("app.llm.probe.httpx.Client", fail_if_client_created)
    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("SMV2_EMBED_MODEL", "nomic-embed-text")

    for raw_url in unsafe_urls:
        monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", raw_url)

        resp = client.post("/api/llm/status/check")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["available"] is False
        assert payload["failure_category"] == "unreachable"
        assert raw_url not in resp.text

    assert created_clients == 0


def test_llm_status_check_rejects_oversized_ollama_show_stream_before_json_parse(
    client, monkeypatch
):
    from app.llm import probe

    parsed_json = False

    class OversizedResponse:
        status_code = 200
        is_redirect = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield b"{"
            yield b'"padding":"' + (b"x" * probe._MAX_RESPONSE_BYTES) + b'"}'

        def json(self):
            nonlocal parsed_json
            parsed_json = True
            return {"capabilities": ["completion"]}

    class OversizedClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def stream(self, method: str, path: str, *, json: dict):
            return OversizedResponse()

    monkeypatch.setattr("app.llm.probe.httpx.Client", OversizedClient)
    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("SMV2_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    assert resp.json()["available"] is False
    assert resp.json()["failure_category"] == "unreachable"
    assert parsed_json is False


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
    provider_changed_without_endpoint = client.get("/api/llm/status").json()
    assert provider_changed_without_endpoint["provider"] == "ollama"
    assert provider_changed_without_endpoint["configured"] is False
    assert provider_changed_without_endpoint["available"] is False

    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    provider_changed_with_endpoint = client.get("/api/llm/status").json()
    assert provider_changed_with_endpoint["provider"] == "ollama"
    assert provider_changed_with_endpoint["available"] is True
    assert provider_changed_with_endpoint["capabilities"] == {"completion": True, "embeddings": True}


def test_llm_status_check_calls_ollama_probe_without_metering(client, monkeypatch):
    calls = _patch_ollama_probe(
        monkeypatch,
        {
            "llama3.2": ["completion"],
            "nomic-embed-text": ["embedding"],
        },
    )

    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("SMV2_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    calls_before = _llm_call_count()

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "ollama"
    assert body["model"] == "llama3.2"
    assert body["available"] is True
    assert body["capabilities"] == {"completion": True, "embeddings": True}
    assert body["failure_category"] is None
    assert [call for call in calls if call.get("path") == "/api/show"] == [
        {"path": "/api/show", "name": "llama3.2"},
        {"path": "/api/show", "name": "nomic-embed-text"},
    ]
    assert _llm_call_count() == calls_before


def test_llm_status_check_reports_missing_configured_ollama_completion_model(
    client, monkeypatch
):
    calls = _patch_ollama_probe(
        monkeypatch,
        {
            "nomic-embed-text": ["embedding"],
        },
    )
    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("SMV2_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["available"] is False
    assert payload["capabilities"]["completion"] is False
    assert payload["failure_category"] == "ollama_model_unavailable"
    client_kwargs = calls[0]["client_kwargs"]
    assert client_kwargs["base_url"] == "http://127.0.0.1:11434"
    assert client_kwargs["follow_redirects"] is False
    assert client_kwargs["timeout"].connect == 1.0
    assert client_kwargs["timeout"].read == 5.0
    assert calls[1:] == [
        {"path": "/api/show", "name": "llama3.2"},
        {"path": "/api/show", "name": "nomic-embed-text"},
    ]


def test_llm_status_check_allows_ollama_completion_when_embed_model_missing(
    client, monkeypatch
):
    _patch_ollama_probe(
        monkeypatch,
        {
            "llama3.2": ["completion"],
        },
    )
    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("SMV2_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["available"] is True
    assert payload["capabilities"] == {"completion": True, "embeddings": False}
    assert payload["failure_category"] == "ollama_embed_model_unavailable"


def test_ollama_generation_preflight_refreshes_stale_checks_and_reuses_fresh_success(
    client, ingest_course, monkeypatch
):
    model_capabilities = {
        "llama3.2": ["completion"],
        "nomic-embed-text": ["embedding"],
    }
    calls = _patch_ollama_probe(monkeypatch, model_capabilities)
    monotonic = {"now": 100.0}
    from app.services import llm_readiness_service

    monkeypatch.setattr(
        llm_readiness_service,
        "time",
        SimpleNamespace(monotonic=lambda: monotonic["now"]),
        raising=False,
    )
    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("SMV2_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    ready = client.post("/api/llm/status/check")
    fresh_generation = client.post(f"/api/sections/{section_id}/lesson")
    model_capabilities.pop("llama3.2")
    monotonic["now"] = 131.0
    stale_generation = client.post(f"/api/sections/{section_id}/lesson?force=true")

    assert ready.status_code == 200
    assert fresh_generation.status_code == 202
    assert stale_generation.status_code == 503
    assert stale_generation.json()["detail"]["failure_category"] == "ollama_model_unavailable"
    show_calls = [call for call in calls if call.get("path") == "/api/show"]
    assert show_calls == [
        {"path": "/api/show", "name": "llama3.2"},
        {"path": "/api/show", "name": "nomic-embed-text"},
        {"path": "/api/show", "name": "llama3.2"},
        {"path": "/api/show", "name": "nomic-embed-text"},
    ]
    session = get_session()
    try:
        assert session.query(Job).filter(Job.type == "generate_lesson").count() == 1
    finally:
        session.close()
