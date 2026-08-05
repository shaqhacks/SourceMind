from __future__ import annotations

import tomllib

from app.config import data_dir


def _csrf_headers(client) -> dict[str, str]:
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    return {
        "X-CSRF-Token": token,
        "origin": "http://testserver",
        "host": "testserver",
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
    assert body["credentials"]["anthropic_api_key"] == "[redacted]"
    assert "sk-ant-test-secret" not in get_resp.text

    local_settings = tomllib.loads((data_dir() / "local_settings.toml").read_text())
    secrets = tomllib.loads((data_dir() / "secrets.toml").read_text())
    assert local_settings == {"model": "claude-3-5-sonnet-latest", "provider": "anthropic"}
    assert secrets["anthropic_api_key"] == "sk-ant-test-secret"


def test_settings_clear_removes_only_selected_provider_credential(client):
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


def test_settings_check_flow_reports_ready_after_local_ollama_selection(client, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

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
