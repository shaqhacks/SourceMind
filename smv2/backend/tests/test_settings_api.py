from __future__ import annotations


def _csrf_headers(client) -> dict[str, str]:
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    return {
        "x-smv2-csrf": token,
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


def test_settings_check_flow_reports_ready_after_local_ollama_selection(client, stub_provider):
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
    assert body["model"] == "stub-model"
    assert body["available"] is True
    assert stub_provider.call_count == 1
