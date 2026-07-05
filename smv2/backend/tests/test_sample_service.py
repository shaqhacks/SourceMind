from __future__ import annotations

import asyncio

from app.config import data_dir
from app.services import sample_service


def _run_seed() -> None:
    asyncio.run(sample_service.seed_sample_course_if_first_run())


def test_seeds_via_lifespan_when_empty_and_enabled(client_with_sample_course):
    """End-to-end: the fixture's TestClient enters (running lifespan) with
    sample_course_enabled=1 against an empty DB, so seeding should have
    already happened by the time the test body runs.
    """
    courses = client_with_sample_course.get("/api/courses").json()
    assert len(courses) == 1
    assert courses[0]["title"] == "Welcome to SourceMind"

    jobs = client_with_sample_course.get("/api/jobs").json()
    ingest_jobs = [j for j in jobs if j["type"] == "ingest"]
    assert len(ingest_jobs) == 1
    assert ingest_jobs[0]["payload"]["course_id"] == courses[0]["id"]
    assert ingest_jobs[0]["status"] == "queued"  # worker disabled in tests

    assert (data_dir() / "sample_seeded").exists()


def test_skips_when_a_course_already_exists(client, monkeypatch):
    client.post("/api/courses", json={"title": "My Own Course"})

    monkeypatch.setenv("SMV2_SAMPLE_COURSE_ENABLED", "1")
    _run_seed()

    courses = client.get("/api/courses").json()
    assert len(courses) == 1
    assert courses[0]["title"] == "My Own Course"
    assert not (data_dir() / "sample_seeded").exists()


def test_skips_when_marker_present_even_with_empty_table(client, monkeypatch):
    marker = data_dir() / "sample_seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("already seeded in a previous run\n")

    monkeypatch.setenv("SMV2_SAMPLE_COURSE_ENABLED", "1")
    _run_seed()

    courses = client.get("/api/courses").json()
    assert courses == []


def test_skips_when_disabled(client):
    # SMV2_SAMPLE_COURSE_ENABLED=0 is the client fixture's default.
    _run_seed()

    courses = client.get("/api/courses").json()
    assert courses == []
    assert not (data_dir() / "sample_seeded").exists()


def test_seed_is_idempotent_across_repeated_calls(client, monkeypatch):
    """Calling seed_sample_course_if_first_run twice in a row (simulating
    two app restarts against the same data dir) must not create a second
    course the second time.
    """
    monkeypatch.setenv("SMV2_SAMPLE_COURSE_ENABLED", "1")
    _run_seed()
    _run_seed()

    courses = client.get("/api/courses").json()
    assert len(courses) == 1
