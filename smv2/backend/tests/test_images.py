"""ADR-018: image extraction during ingest + the endpoint that serves them.

Covers the full path: pymupdf4llm writes embedded raster images to disk
with deterministic (page+index, not random) filenames during ingest,
body_md gets those refs rewritten to servable API paths, the endpoint
serves only from a course's own images directory, and both re-ingest and
course-delete clean the directory up (REPLACED bucket semantics).
"""

from __future__ import annotations

import pytest

from app.config import data_dir
from app.services import images_service


def test_ingest_writes_image_with_deterministic_filename(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("images.pdf")
    asset_id = upload_resp.json()["id"]

    images_dir = data_dir() / "assets" / course_id / "images"
    assert images_dir.is_dir()
    written = sorted(p.name for p in images_dir.iterdir())
    assert written == [f"{asset_id}-0-0.png"]


def test_ingest_rewrites_image_ref_to_api_path(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("images.pdf")
    asset_id = upload_resp.json()["id"]

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    detail = client.get(f"/api/sections/{sections[0]['id']}").json()

    assert f"![](/api/courses/{course_id}/images/{asset_id}-0-0.png)" in detail["body_md"]
    # The local filesystem path pymupdf4llm originally wrote must never
    # leak into persisted content.
    assert str(data_dir()) not in detail["body_md"]


def test_get_course_image_serves_the_file(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("images.pdf")
    asset_id = upload_resp.json()["id"]

    resp = client.get(f"/api/courses/{course_id}/images/{asset_id}-0-0.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content  # non-empty image bytes

    on_disk = (data_dir() / "assets" / course_id / "images" / f"{asset_id}-0-0.png").read_bytes()
    assert resp.content == on_disk


def test_get_course_image_404_for_missing_file(client, ingest_course):
    course_id, *_ = ingest_course("images.pdf")

    resp = client.get(f"/api/courses/{course_id}/images/does-not-exist.png")
    assert resp.status_code == 404


def test_get_course_image_404_for_missing_course(client):
    resp = client.get("/api/courses/no-such-course/images/anything.png")
    assert resp.status_code == 404


def test_get_course_image_400_for_path_traversal_attempt(client, ingest_course):
    course_id, *_ = ingest_course("images.pdf")

    # A literal ".." sent unencoded gets collapsed by the HTTP client itself
    # (RFC 3986 dot-segment removal) before the request is even sent, so it
    # never reaches this route at all -- %2e%2e is what a real attacker
    # sending a raw request would use to actually get a literal ".." into
    # the filename path parameter our handler receives.
    resp = client.get(f"/api/courses/{course_id}/images/%2e%2e")
    assert resp.status_code == 400


def test_resolve_image_path_rejects_dot_dot_even_though_it_matches_the_allowlist(tmp_path, monkeypatch):
    """"." and "-" are both allowed by the filename allowlist regex, so ".."
    passes it -- the explicit containment check is what actually stops this
    from resolving outside the images directory, not the regex alone.
    """
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    course_dir = tmp_path / "assets" / "course-x" / "images"
    course_dir.mkdir(parents=True)
    (course_dir / "real.png").write_bytes(b"fake-png-bytes")

    with pytest.raises(images_service.InvalidImageFilenameError):
        images_service.resolve_image_path("course-x", "..")


def test_resolve_image_path_rejects_separators_and_control_chars(tmp_path, monkeypatch):
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    for bad in ["../secret.png", "a/b.png", "a\\b.png", ""]:
        with pytest.raises(images_service.InvalidImageFilenameError):
            images_service.resolve_image_path("course-x", bad)


def test_resolve_image_path_returns_real_file_inside_the_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    course_dir = tmp_path / "assets" / "course-x" / "images"
    course_dir.mkdir(parents=True)
    target = course_dir / "real.png"
    target.write_bytes(b"fake-png-bytes")

    resolved = images_service.resolve_image_path("course-x", "real.png")
    assert resolved == target.resolve()


def test_reingest_wipes_and_regenerates_the_images_directory(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("images.pdf")
    asset_id = upload_resp.json()["id"]
    images_dir = data_dir() / "assets" / course_id / "images"
    first_run = sorted(p.name for p in images_dir.iterdir())

    from app.jobs.worker import run_due_jobs_once

    resp = client.post(f"/api/courses/{course_id}/ingest")
    assert resp.status_code == 202
    assert run_due_jobs_once() is True

    second_run = sorted(p.name for p in images_dir.iterdir())
    # Same asset, same deterministic filenames -- REPLACED semantics means
    # the directory was wiped and rewritten, not merely left alone; the
    # observable result for an unchanged asset is identical contents.
    assert first_run == second_run == [f"{asset_id}-0-0.png"]


def test_course_delete_removes_the_images_directory(client, ingest_course):
    course_id, *_ = ingest_course("images.pdf")
    images_dir = data_dir() / "assets" / course_id / "images"
    assert images_dir.is_dir()

    resp = client.delete(f"/api/courses/{course_id}")
    assert resp.status_code == 204
    assert not images_dir.exists()


def test_page_without_images_is_unaffected(client, ingest_course):
    """images.pdf's second page has no embedded image of its own -- confirm
    its text still made it into a section body untouched, and that no
    image ref was invented for it.
    """
    course_id, *_ = ingest_course("images.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    detail = client.get(f"/api/sections/{sections[0]['id']}").json()

    assert "This second page has no image of its own" in detail["body_md"]
    assert detail["body_md"].count("![](") == 1
