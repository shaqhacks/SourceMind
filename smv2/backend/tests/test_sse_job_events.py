from __future__ import annotations

import json

from app.jobs.worker import run_due_jobs_once
from app.security.local_settings import csrf_token


def test_job_events_stream_reaches_terminal_status(client):
    resp = client.post("/api/jobs", json={"type": "noop"})
    job_id = resp.json()["id"]

    # This TestClient's stream() drains the full response before returning
    # from __enter__ (it isn't concurrent with this thread), so the job
    # must already be terminal before the stream opens — the endpoint's
    # first poll should then immediately see the terminal status and close.
    assert run_due_jobs_once() is True

    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")

        for line in stream.iter_lines():
            if not line.startswith("data:"):
                continue
            events.append(json.loads(line[len("data:") :].strip()))

    assert len(events) == 1
    assert events[0]["id"] == job_id
    assert events[0]["status"] == "succeeded"


def test_job_events_stream_emits_cancelled_terminal_status_and_closes(client):
    resp = client.post("/api/jobs", json={"type": "noop"})
    job_id = resp.json()["id"]
    cancel_resp = client.post(
        f"/api/jobs/{job_id}/cancel",
        headers={
            "X-CSRF-Token": csrf_token(),
            "Origin": "http://localhost:3000",
            "Host": "localhost:8000",
        },
    )
    assert cancel_resp.status_code == 200

    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")

        for line in stream.iter_lines():
            if not line.startswith("data:"):
                continue
            events.append(json.loads(line[len("data:") :].strip()))

    assert len(events) == 1
    assert events[0]["id"] == job_id
    assert events[0]["status"] == "cancelled"


def test_job_events_404_for_missing_job(client):
    resp = client.get("/api/jobs/does-not-exist/events")
    assert resp.status_code == 404
