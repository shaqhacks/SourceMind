from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException, Request

from app.security.local_settings import (
    CSRF_HEADER_NAME,
    csrf_token,
    normalize_ollama_base_url,
    require_local_settings_write,
)


def _settings_headers(token: str, **overrides: str) -> dict[str, str]:
    headers = {
        "X-CSRF-Token": token,
        "Origin": "http://testserver",
        "Host": "testserver",
    }
    headers.update(overrides)
    return headers


def _local_settings_request(headers: dict[str, str], *, client_host: str = "testclient") -> Request:
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/settings",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": (client_host, 50000),
            "server": ("localhost", 8000),
            "scheme": "http",
        }
    )


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
            "X-CSRF-Token": token,
            "origin": "http://testserver",
            "host": "testserver",
            "x-forwarded-for": "203.0.113.9",
        },
    )

    assert resp.status_code == 403
    assert "loopback" in resp.json()["detail"]


def test_settings_write_requires_csrf_token(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://testserver")

    resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={"Origin": "http://testserver", "Host": "testserver"},
    )

    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"]


def test_settings_write_accepts_plan_csrf_header_and_rejects_legacy_header(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://testserver")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    base_headers = {"Origin": "http://testserver", "Host": "testserver"}

    legacy_resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={**base_headers, "x-smv2-csrf": token},
    )
    assert legacy_resp.status_code == 403

    resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={**base_headers, "X-CSRF-Token": token},
    )
    assert resp.status_code == 200


def test_settings_write_rejects_mismatched_origin(client):
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={
            "X-CSRF-Token": token,
            "origin": "https://evil.example",
            "host": "testserver",
        },
    )

    assert resp.status_code == 403
    assert "origin" in resp.json()["detail"].lower()


def test_settings_redacts_secret_material_from_responses_and_logs(client, caplog, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://testserver")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    secret = "sk-ant-log-secret"
    caplog.set_level(logging.INFO)

    resp = client.put(
        "/api/settings",
        json={"provider": "anthropic", "credentials": {"anthropic_api_key": secret}},
        headers={
            "X-CSRF-Token": token,
            "origin": "http://testserver",
            "host": "testserver",
        },
    )

    assert resp.status_code == 200
    assert secret not in resp.text
    assert secret not in caplog.text


def test_settings_mutation_responses_are_no_store(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://testserver")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    headers = {
        "X-CSRF-Token": token,
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


def test_settings_write_accepts_configured_loopback_origin_across_ports(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://localhost:3000")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    response = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={
            "X-CSRF-Token": token,
            "Origin": "http://localhost:3000",
            "Host": "localhost:8000",
        },
    )

    assert response.status_code == 200


def test_settings_write_rejects_missing_origin(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://localhost:3000")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    response = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={"X-CSRF-Token": token, "Host": "localhost:8000"},
    )

    assert response.status_code == 403


def test_settings_write_rejects_null_origin(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://localhost:3000")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    response = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers=_settings_headers(token, Origin="null", Host="localhost:8000"),
    )

    assert response.status_code == 403


def test_settings_write_rejects_unconfigured_loopback_origin_port(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://localhost:3000")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    response = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers=_settings_headers(token, Origin="http://localhost:3001", Host="localhost:8000"),
    )

    assert response.status_code == 403


def test_settings_write_rejects_https_non_loopback_origin(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://localhost:3000")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    response = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers=_settings_headers(token, Origin="https://evil.example", Host="localhost:8000"),
    )

    assert response.status_code == 403


def test_settings_write_rejects_missing_json_content_type(monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://localhost:3000")
    request = _local_settings_request(
        {
            CSRF_HEADER_NAME: csrf_token(),
            "Origin": "http://localhost:3000",
            "Host": "localhost:8000",
        }
    )

    with pytest.raises(HTTPException) as exc:
        require_local_settings_write(request)
    assert exc.value.status_code == 403
    assert "json" in exc.value.detail.lower()


def test_settings_write_rejects_non_loopback_api_host(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://localhost:3000")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]

    response = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers=_settings_headers(token, Origin="http://localhost:3000", Host="api.example:8000"),
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost", "http://127.0.0.1:11434"),
        ("http://localhost:11434/", "http://127.0.0.1:11434"),
        ("http://127.0.0.1:11435", "http://127.0.0.1:11435"),
        ("http://[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_normalize_ollama_base_url_accepts_only_canonical_loopback(raw, expected):
    assert normalize_ollama_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://localhost:11434",
        "http://user:pass@localhost:11434",
        "http://localhost:11434?x=1",
        "http://localhost:11434#fragment",
        "http://localhost:11434/api",
        "http://127.1:11434",
        "http://2130706433:11434",
        "http://0177.0.0.1:11434",
        "http://0x7f.0.0.1:11434",
        "http://[::ffff:127.0.0.1]:11434",
        "http://0.0.0.0:11434",
        "http://[::]:11434",
        "http://[fe80::1]:11434",
        "http://192.168.1.10:11434",
        "http://8.8.8.8:11434",
        "http://localhost:0",
        "http://localhost:000",
        "http://localhost:",
        "http://localhost:notaport",
    ],
)
def test_normalize_ollama_base_url_rejects_unsafe_urls_without_echoing_input(raw):
    with pytest.raises(ValueError) as exc:
        normalize_ollama_base_url(raw)

    assert raw not in str(exc.value)
