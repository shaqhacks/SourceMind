from __future__ import annotations

import logging


def test_settings_bootstrap_is_no_store_and_returns_csrf_token(client):
    resp = client.get("/api/settings/bootstrap")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["csrf_token"]
    assert body["rollout"]["local_settings_enabled"] is True


def test_settings_write_rejects_non_loopback_client(client):
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={
            "x-smv2-csrf": token,
            "origin": "http://testserver",
            "host": "testserver",
            "x-forwarded-for": "203.0.113.9",
        },
    )

    assert resp.status_code == 403
    assert "loopback" in resp.json()["detail"]


def test_settings_write_requires_csrf_token(client):
    resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={"origin": "http://testserver", "host": "testserver"},
    )

    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"]


def test_settings_write_rejects_mismatched_origin(client):
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={
            "x-smv2-csrf": token,
            "origin": "https://evil.example",
            "host": "testserver",
        },
    )

    assert resp.status_code == 403
    assert "origin" in resp.json()["detail"].lower()


def test_settings_redacts_secret_material_from_responses_and_logs(client, caplog):
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    secret = "sk-ant-log-secret"
    caplog.set_level(logging.INFO)

    resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "credentials": {"anthropic_api_key": secret}},
        headers={
            "x-smv2-csrf": token,
            "origin": "http://testserver",
            "host": "testserver",
        },
    )

    assert resp.status_code == 200
    assert secret not in resp.text
    assert secret not in caplog.text


def test_settings_mutation_responses_are_no_store(client):
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    headers = {
        "x-smv2-csrf": token,
        "origin": "http://testserver",
        "host": "testserver",
    }

    put_resp = client.put(
        "/api/settings",
        json={
            "provider": "anthropic",
            "credentials": {"anthropic_api_key": "sk-ant-no-store"},
        },
        headers=headers,
    )
    assert put_resp.status_code == 200
    assert put_resp.headers["cache-control"] == "no-store"

    delete_resp = client.request(
        "DELETE",
        "/api/settings",
        json={"provider": "anthropic", "confirmation": "clear anthropic credential"},
        headers=headers,
    )
    assert delete_resp.status_code == 200
    assert delete_resp.headers["cache-control"] == "no-store"
