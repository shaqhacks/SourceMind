from __future__ import annotations

from fastapi.responses import JSONResponse


def test_health_response_includes_minimal_security_headers(client):
    resp = client.get("/health")

    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in resp.headers


def test_endpoint_specific_security_headers_override_global_defaults(client):
    @client.app.get("/test-only/security-header-override")
    async def security_header_override():
        return JSONResponse(
            {"status": "ok"},
            headers={"X-Frame-Options": "DENY"},
        )

    resp = client.get("/test-only/security-header-override")

    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
