from __future__ import annotations

from app.jobs.worker import run_due_jobs_once


def test_worker_claims_each_queued_job_exactly_once(client):
    resp1 = client.post("/api/jobs", json={"type": "noop"})
    resp2 = client.post("/api/jobs", json={"type": "noop"})
    job_id_1 = resp1.json()["id"]
    job_id_2 = resp2.json()["id"]

    assert run_due_jobs_once() is True
    assert run_due_jobs_once() is True
    assert run_due_jobs_once() is False

    for job_id in (job_id_1, job_id_2):
        body = client.get(f"/api/jobs/{job_id}").json()
        assert body["status"] == "succeeded"
        assert body["attempts"] == 1
