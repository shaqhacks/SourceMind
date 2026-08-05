from __future__ import annotations

from app.llm.provider import CompletionResult


def test_llm_status_reports_readiness_without_network_call(client, monkeypatch):
    def fail_if_provider_constructed():
        raise AssertionError("status must not construct or call the provider")

    monkeypatch.setattr("app.services.llm_readiness_service.get_provider", fail_if_provider_constructed)

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


def test_llm_status_check_updates_last_check_and_capabilities(client, stub_provider):
    stub_provider.responses = [
        CompletionResult(text="ok", input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["available"] is True
    assert body["provider"] == "anthropic"
    assert body["model"] == "stub-model"
    assert body["capabilities"] == {"completion": True, "embeddings": True}
    assert body["failure_category"] is None
    assert body["last_checked_at"] is not None
    assert stub_provider.call_count == 1


def test_llm_status_redacts_secret_material_from_failures(client, monkeypatch):
    secret = "sk-ant-secret-value"

    class SecretFailureProvider:
        model_name = "secret-model"
        supports_embeddings = False

        def complete(self, *args, **kwargs):
            raise RuntimeError(f"provider rejected key {secret}")

    monkeypatch.setattr("app.services.llm_readiness_service.get_provider", lambda: SecretFailureProvider())

    resp = client.post("/api/llm/status/check")

    assert resp.status_code == 200
    serialized = resp.text
    assert secret not in serialized
    assert "[redacted]" in serialized
    body = resp.json()
    assert body["available"] is False
    assert body["failure_category"] == "provider_error"
