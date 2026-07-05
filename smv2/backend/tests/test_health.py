from __future__ import annotations


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "version": "0.1.0"}
