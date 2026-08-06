from __future__ import annotations

import tomllib

import pytest
from fastapi import HTTPException

from app.config import data_dir
from app.routers import settings as settings_router
from app.services.ollama_discovery_service import OllamaDiscoveryError


def _csrf_headers(client) -> dict[str, str]:
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    return {
        "X-CSRF-Token": token,
        "origin": "http://localhost:3000",
        "host": "localhost:3000",
    }


def test_settings_round_trips_provider_model_and_redacted_credentials(client):
    headers = _csrf_headers(client)

    resp = client.put(
        "/api/settings",
        json={
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-latest",
            "credentials": {"anthropic_api_key": "sk-ant-test-secret"},
        },
        headers=headers,
    )
    assert resp.status_code == 200

    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-3-5-sonnet-latest"
    assert body["credentials_present"]["anthropic"] is True
    assert body["credentials"] == {}
    assert "sk-ant-test-secret" not in get_resp.text

    local_settings = tomllib.loads((data_dir() / "local_settings.toml").read_text())
    secrets = tomllib.loads((data_dir() / "secrets.toml").read_text())
    assert local_settings == {
        "model": "claude-3-5-sonnet-latest",
        "provider": "anthropic",
    }
    assert secrets["anthropic_api_key"] == "sk-ant-test-secret"


def test_settings_clear_removes_only_selected_provider_credential(client, monkeypatch):
    async def fake_discover(base_url: str) -> list[str]:
        assert base_url == "http://127.0.0.1:11434"
        return ["llama3.2"]

    monkeypatch.setattr("app.routers.settings.discover_ollama_models", fake_discover)
    headers = _csrf_headers(client)
    put_resp = client.put(
        "/api/settings",
        json={
            "provider": "ollama",
            "model": "llama3.2",
            "credentials": {
                "anthropic_api_key": "sk-ant-test-secret",
                "ollama_base_url": "http://127.0.0.1:11434",
            },
        },
        headers=headers,
    )
    assert put_resp.status_code == 200

    clear_resp = client.request(
        "DELETE",
        "/api/settings",
        json={"provider": "anthropic", "confirmation": "clear anthropic credential"},
        headers=headers,
    )

    assert clear_resp.status_code == 200
    body = client.get("/api/settings").json()
    assert body["credentials_present"]["anthropic"] is False
    assert body["credentials_present"]["ollama"] is True
    assert body["provider"] == "ollama"
    assert body["model"] == "llama3.2"

    secrets = tomllib.loads((data_dir() / "secrets.toml").read_text())
    assert "anthropic_api_key" not in secrets
    assert secrets["ollama_base_url"] == "http://127.0.0.1:11434"


def test_settings_check_flow_reports_ready_after_local_ollama_selection(
    client, monkeypatch
):
    async def fake_discover(base_url: str) -> list[str]:
        assert base_url == "http://127.0.0.1:11434"
        return ["llama3.2"]

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr("app.routers.settings.discover_ollama_models", fake_discover)
    monkeypatch.setattr(
        "app.llm.probe.httpx.get",
        lambda url, *, timeout: FakeResponse(),
    )
    headers = _csrf_headers(client)
    put_resp = client.put(
        "/api/settings",
        json={
            "provider": "ollama",
            "model": "llama3.2",
            "credentials": {"ollama_base_url": "http://127.0.0.1:11434"},
        },
        headers=headers,
    )
    assert put_resp.status_code == 200

    check_resp = client.post("/api/llm/status/check")

    assert check_resp.status_code == 200
    body = check_resp.json()
    assert body["provider"] == "ollama"
    assert body["model"] == "llama3.2"
    assert body["available"] is True
    assert body["failure_category"] is None


def test_settings_response_does_not_treat_default_ollama_url_as_configured_or_return_endpoint(
    client,
):
    resp = client.get("/api/settings")

    assert resp.status_code == 200
    body = resp.json()
    assert body["credentials_present"]["ollama"] is False
    assert body["credentials"] == {}
    assert "localhost:11434" not in resp.text


def test_settings_response_omits_stored_ollama_endpoint_string(client, monkeypatch):
    async def fake_discover(base_url: str) -> list[str]:
        assert base_url == "http://127.0.0.1:11434"
        return ["llama3.2"]

    monkeypatch.setattr("app.routers.settings.discover_ollama_models", fake_discover)
    headers = _csrf_headers(client)
    secret_endpoint = "http://localhost:11434"
    put_resp = client.put(
        "/api/settings",
        json={
            "provider": "ollama",
            "model": "llama3.2",
            "credentials": {"ollama_base_url": secret_endpoint},
        },
        headers=headers,
    )
    assert put_resp.status_code == 200

    get_resp = client.get("/api/settings")

    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["credentials_present"]["ollama"] is True
    assert body["credentials"] == {}
    assert secret_endpoint not in get_resp.text


def test_ollama_models_route_discovers_models_and_reports_configured_model_absent(
    client,
    monkeypatch,
):
    async def fake_discover(base_url: str) -> list[str]:
        assert base_url == "http://127.0.0.1:11434"
        return ["llama3.2:latest"]

    monkeypatch.setattr(
        "app.routers.settings.discover_ollama_models", fake_discover, raising=False
    )
    headers = _csrf_headers(client)

    resp = client.post(
        "/api/settings/ollama/models",
        json={
            "base_url": "http://localhost:11434",
            "configured_model": "missing:latest",
        },
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "models": ["llama3.2:latest"],
        "configured_model": "missing:latest",
        "configured_model_available": False,
    }


def test_ollama_models_route_requires_csrf_before_discovery(client, monkeypatch):
    calls = 0

    async def fake_discover(base_url: str) -> list[str]:
        nonlocal calls
        calls += 1
        return ["llama3.2:latest"]

    monkeypatch.setattr(
        "app.routers.settings.discover_ollama_models", fake_discover, raising=False
    )

    resp = client.post(
        "/api/settings/ollama/models",
        json={"base_url": "http://localhost:11434"},
        headers={"origin": "http://localhost:3000", "host": "localhost:3000"},
    )

    assert resp.status_code == 403
    assert calls == 0


def test_ollama_settings_save_rejects_model_missing_from_discovery_without_mutation(
    client,
    monkeypatch,
):
    async def fake_discover(base_url: str) -> list[str]:
        assert base_url == "http://127.0.0.1:11434"
        return ["llama3.2:latest"]

    monkeypatch.setattr("app.routers.settings.discover_ollama_models", fake_discover)
    headers = _csrf_headers(client)

    resp = client.put(
        "/api/settings",
        json={
            "provider": "ollama",
            "model": "missing:latest",
            "credentials": {"ollama_base_url": "http://localhost:11434"},
        },
        headers=headers,
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["failure_category"] == "ollama_model_unavailable"
    assert not (data_dir() / "local_settings.toml").exists()
    assert not (data_dir() / "secrets.toml").exists()
    assert "http://localhost:11434" not in resp.text


def test_ollama_settings_save_accepts_exact_discovered_model_and_redacts_endpoint(
    client,
    monkeypatch,
):
    async def fake_discover(base_url: str) -> list[str]:
        assert base_url == "http://127.0.0.1:11434"
        return ["llama3.2:latest", "llama3.2"]

    monkeypatch.setattr("app.routers.settings.discover_ollama_models", fake_discover)
    headers = _csrf_headers(client)

    resp = client.put(
        "/api/settings",
        json={
            "provider": "ollama",
            "model": "llama3.2:latest",
            "credentials": {"ollama_base_url": "http://localhost:11434"},
        },
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "ollama"
    assert body["model"] == "llama3.2:latest"
    assert body["credentials_present"]["ollama"] is True
    assert body["credentials"] == {}
    assert "http://127.0.0.1:11434" not in resp.text

    local_settings = tomllib.loads((data_dir() / "local_settings.toml").read_text())
    secrets = tomllib.loads((data_dir() / "secrets.toml").read_text())
    assert local_settings == {"model": "llama3.2:latest", "provider": "ollama"}
    assert secrets["ollama_base_url"] == "http://127.0.0.1:11434"


def test_ollama_settings_save_requires_exact_mixed_case_model_membership(
    client,
    monkeypatch,
):
    async def fake_discover(base_url: str) -> list[str]:
        assert base_url == "http://127.0.0.1:11434"
        return ["Llama3.2:Latest"]

    monkeypatch.setattr("app.routers.settings.discover_ollama_models", fake_discover)
    headers = _csrf_headers(client)

    lower_resp = client.put(
        "/api/settings",
        json={
            "provider": "ollama",
            "model": "llama3.2:latest",
            "credentials": {"ollama_base_url": "http://localhost:11434"},
        },
        headers=headers,
    )

    assert lower_resp.status_code == 409
    assert lower_resp.json()["detail"]["failure_category"] == "ollama_model_unavailable"
    assert not (data_dir() / "local_settings.toml").exists()
    assert not (data_dir() / "secrets.toml").exists()

    exact_resp = client.put(
        "/api/settings",
        json={
            "provider": "ollama",
            "model": "Llama3.2:Latest",
            "credentials": {"ollama_base_url": "http://localhost:11434"},
        },
        headers=headers,
    )

    assert exact_resp.status_code == 200
    local_settings = tomllib.loads((data_dir() / "local_settings.toml").read_text())
    assert local_settings["model"] == "Llama3.2:Latest"


@pytest.mark.anyio
async def test_ollama_discovery_http_error_suppresses_raw_service_cause(monkeypatch):
    async def fake_discover(base_url: str) -> list[str]:
        unsafe = RuntimeError("http://127.0.0.1:11434/api/tags?token=upstream-secret")
        raise OllamaDiscoveryError(
            "ollama_unreachable",
            "Ollama could not be reached.",
            status_code=503,
        ) from unsafe

    monkeypatch.setattr(settings_router, "discover_ollama_models", fake_discover)

    with pytest.raises(HTTPException) as exc_info:
        await settings_router._discover_ollama_models_or_http_error(
            "http://127.0.0.1:11434"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.__cause__ is None
    assert "upstream-secret" not in repr(exc_info.value)


def test_ollama_invalid_url_http_error_suppresses_raw_value_error_cause():
    with pytest.raises(HTTPException) as exc_info:
        settings_router._resolve_ollama_base_url(
            "http://127.0.0.1:11434/api/tags?token=upstream-secret"
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.__cause__ is None
    assert "upstream-secret" not in repr(exc_info.value)
