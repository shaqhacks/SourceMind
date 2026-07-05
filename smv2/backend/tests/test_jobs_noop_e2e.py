from __future__ import annotations

from app.jobs.worker import run_due_jobs_once


def test_noop_job_end_to_end(client):
    resp = client.post("/api/jobs", json={"type": "noop"})
    assert resp.status_code == 202
    created = resp.json()
    assert created["status"] == "queued"
    assert created["type"] == "noop"
    job_id = created["id"]

    claimed = run_due_jobs_once()
    assert claimed is True

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"ok": True}
    assert body["attempts"] == 1
    assert body["error"] is None


def test_unknown_job_type_is_422(client):
    resp = client.post("/api/jobs", json={"type": "does-not-exist"})
    assert resp.status_code == 422


def test_get_missing_job_is_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404
