"""ADR-020: pdf2htmlEX per-page HTML conversion — a Docker-gated,
post-ingest enhancement job. All docker/subprocess calls are mocked here;
this suite never invokes real Docker (see smv2-ops-data-safety-style live
verification for that, done separately outside the test suite).
"""

from __future__ import annotations

import json

import fitz
import pytest

from app.config import data_dir
from app.db.engine import get_session
from app.db.models import Asset, Job
from app.jobs.worker import run_due_jobs_once
from app.pipeline import html_conversion
from app.pipeline.html_conversion import HtmlConversionError, html_dir


def _fake_convert_factory(*, raise_for_stems: set[str] | None = None, extra_css: str = ""):
    """Builds a fake _docker_convert that writes real page{N}.html + shared.css
    files into the given out_dir, matching the real PDF's actual page count
    (read via fitz, same as production code) — so _convert_one_asset's own
    "did the converter produce every expected page" check passes exactly
    like it would against the real tool.
    """
    calls = []

    def _fake(image, pdf_path, out_dir):
        calls.append({"image": image, "pdf_path": pdf_path, "out_dir": out_dir})
        if raise_for_stems and pdf_path.stem in raise_for_stems:
            raise HtmlConversionError("simulated conversion failure")
        doc = fitz.open(str(pdf_path))
        try:
            page_count = doc.page_count
        finally:
            doc.close()
        (out_dir / "shared.css").write_text(f".w0{{width:100px}}{extra_css}", encoding="utf-8")
        for i in range(1, page_count + 1):
            (out_dir / f"page{i}.html").write_text(
                f'<div id="pf{i}" class="pf w0 h0">fake page {i} content</div>', encoding="utf-8"
            )

    return _fake, calls


def _enqueue_convert_html(client, course_id: str) -> str:
    resp = client.post("/api/jobs", json={"type": "convert_html", "payload": {"course_id": course_id}})
    assert resp.status_code == 202
    return resp.json()["id"]


# --- config -----------------------------------------------------------------


def test_html_conversion_enabled_auto_true_when_docker_present(monkeypatch):
    from app import config

    monkeypatch.setenv("SMV2_HTML_CONVERSION", "auto")
    monkeypatch.setattr(config.shutil, "which", lambda name: "/usr/bin/docker")
    assert config.html_conversion_enabled() is True


def test_html_conversion_enabled_auto_false_when_docker_missing(monkeypatch):
    from app import config

    monkeypatch.setenv("SMV2_HTML_CONVERSION", "auto")
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    assert config.html_conversion_enabled() is False


def test_html_conversion_enabled_explicit_override_forces_on(monkeypatch):
    from app import config

    monkeypatch.setenv("SMV2_HTML_CONVERSION", "1")
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    assert config.html_conversion_enabled() is True


def test_html_conversion_enabled_explicit_override_forces_off(monkeypatch):
    from app import config

    monkeypatch.setenv("SMV2_HTML_CONVERSION", "0")
    monkeypatch.setattr(config.shutil, "which", lambda name: "/usr/bin/docker")
    assert config.html_conversion_enabled() is False


def test_docker_image_default_and_env_override(monkeypatch):
    from app import config

    monkeypatch.delenv("SMV2_HTML_DOCKER_IMAGE", raising=False)
    assert config.docker_image() == "pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-alpine-3.12.0-x86_64"

    monkeypatch.setenv("SMV2_HTML_DOCKER_IMAGE", "myorg/my-pdf2htmlex:1.2.3")
    assert config.docker_image() == "myorg/my-pdf2htmlex:1.2.3"


# --- job lifecycle ------------------------------------------------------------


def test_convert_html_success_single_asset(client, ingest_course, monkeypatch):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    monkeypatch.setattr(html_conversion, "_docker_image_present", lambda image: True)
    fake_convert, calls = _fake_convert_factory()
    monkeypatch.setattr(html_conversion, "_docker_convert", fake_convert)

    job_id = _enqueue_convert_html(client, course_id)
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"] == {"course_id": course_id, "converted": 1, "failed": 0}
    assert len(calls) == 1

    session = get_session()
    try:
        asset = session.get(Asset, asset_id)
        assert asset.html_status == "ready"
    finally:
        session.close()

    manifest_path = html_dir(course_id) / asset_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["pages"] == 12
    assert manifest["width_px"] > 0 and manifest["height_px"] > 0

    page1 = (html_dir(course_id) / asset_id / "page1.html").read_text()
    assert "fake page 1 content" in page1
    assert ".w0{width:100px}" in page1  # shared CSS was inlined
    assert "<script" not in page1  # no JS ever gets wrapped in


def test_convert_html_per_asset_isolation(client, monkeypatch):
    resp = client.post("/api/courses", json={"title": "Multi-asset course"})
    course_id = resp.json()["id"]

    from conftest import FIXTURES_DIR

    for name in ("with_bookmarks.pdf", "no_bookmarks.pdf"):
        with (FIXTURES_DIR / name).open("rb") as f:
            client.post(
                f"/api/courses/{course_id}/assets", files={"file": (name, f, "application/pdf")}
            )
    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True

    session = get_session()
    try:
        assets = session.query(Asset).filter(Asset.course_id == course_id).order_by(Asset.created_at.asc()).all()
        good_id, bad_id = assets[0].id, assets[1].id
    finally:
        session.close()

    monkeypatch.setattr(html_conversion, "_docker_image_present", lambda image: True)
    stems = set()
    # The failing asset's stored PDF filename stem is its own asset id.
    stems.add(bad_id)
    fake_convert, calls = _fake_convert_factory(raise_for_stems=stems)
    monkeypatch.setattr(html_conversion, "_docker_convert", fake_convert)

    job_id = _enqueue_convert_html(client, course_id)
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"] == {"course_id": course_id, "converted": 1, "failed": 1}
    assert len(calls) == 2  # both assets attempted despite the first's failure

    session = get_session()
    try:
        assert session.get(Asset, good_id).html_status == "ready"
        assert session.get(Asset, bad_id).html_status == "failed"
    finally:
        session.close()


def test_convert_html_pulls_image_when_missing(client, ingest_course, monkeypatch):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    monkeypatch.setattr(html_conversion, "_docker_image_present", lambda image: False)
    pull_calls = []
    monkeypatch.setattr(html_conversion, "_docker_pull", lambda image: pull_calls.append(image))
    fake_convert, convert_calls = _fake_convert_factory()
    monkeypatch.setattr(html_conversion, "_docker_convert", fake_convert)

    job_id = _enqueue_convert_html(client, course_id)
    assert run_due_jobs_once() is True

    assert len(pull_calls) == 1
    assert len(convert_calls) == 1
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"


def test_convert_html_pull_failure_is_a_clean_job_failure(client, ingest_course, monkeypatch):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    monkeypatch.setattr(html_conversion, "_docker_image_present", lambda image: False)

    def _fail_pull(image):
        raise HtmlConversionError(f"could not pull {image!r} — check Docker is running")

    monkeypatch.setattr(html_conversion, "_docker_pull", _fail_pull)

    job_id = _enqueue_convert_html(client, course_id)
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "Docker" in job["error"]

    session = get_session()
    try:
        assert session.get(Asset, asset_id).html_status == "failed"
    finally:
        session.close()


def test_convert_html_no_assets_is_a_no_op(client):
    resp = client.post("/api/courses", json={"title": "Empty course"})
    course_id = resp.json()["id"]

    job_id = _enqueue_convert_html(client, course_id)
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"] == {"course_id": course_id, "converted": 0, "failed": 0}


# --- ingest wiring --------------------------------------------------------


def test_ingest_does_not_enqueue_convert_html_when_disabled(client, ingest_course):
    # conftest already forces SMV2_HTML_CONVERSION=0 by default.
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        jobs = session.query(Job).filter(Job.type == "convert_html").all()
    finally:
        session.close()
    assert jobs == []


def test_ingest_enqueues_convert_html_when_enabled(client, monkeypatch):
    monkeypatch.setenv("SMV2_HTML_CONVERSION", "1")
    monkeypatch.setattr(html_conversion, "_docker_image_present", lambda image: True)
    fake_convert, calls = _fake_convert_factory()
    monkeypatch.setattr(html_conversion, "_docker_convert", fake_convert)

    resp = client.post("/api/courses", json={"title": "Auto-convert course"})
    course_id = resp.json()["id"]
    from conftest import FIXTURES_DIR

    with (FIXTURES_DIR / "with_bookmarks.pdf").open("rb") as f:
        upload_resp = client.post(
            f"/api/courses/{course_id}/assets",
            files={"file": ("with_bookmarks.pdf", f, "application/pdf")},
        )
    asset_id = upload_resp.json()["id"]

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True  # the ingest job itself
    assert run_due_jobs_once() is True  # the convert_html job it enqueued
    assert run_due_jobs_once() is False  # nothing left

    session = get_session()
    try:
        assert session.get(Asset, asset_id).html_status == "ready"
    finally:
        session.close()


def test_reingest_wipes_html_dir_and_resets_status(client, ingest_course, monkeypatch):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    monkeypatch.setattr(html_conversion, "_docker_image_present", lambda image: True)
    fake_convert, _ = _fake_convert_factory()
    monkeypatch.setattr(html_conversion, "_docker_convert", fake_convert)

    job_id = _enqueue_convert_html(client, course_id)
    assert run_due_jobs_once() is True
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "succeeded"

    asset_html_dir = html_dir(course_id) / asset_id
    assert asset_html_dir.is_dir()

    reingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert reingest_resp.status_code == 202
    assert run_due_jobs_once() is True  # re-ingest itself; SMV2_HTML_CONVERSION still 0 by default here

    assert not asset_html_dir.exists()
    session = get_session()
    try:
        assert session.get(Asset, asset_id).html_status == "none"
    finally:
        session.close()


def test_course_delete_removes_html_dir(client, ingest_course, monkeypatch):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    monkeypatch.setattr(html_conversion, "_docker_image_present", lambda image: True)
    fake_convert, _ = _fake_convert_factory()
    monkeypatch.setattr(html_conversion, "_docker_convert", fake_convert)

    job_id = _enqueue_convert_html(client, course_id)
    assert run_due_jobs_once() is True
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "succeeded"
    assert (html_dir(course_id) / asset_id).is_dir()

    resp = client.delete(f"/api/courses/{course_id}")
    assert resp.status_code == 204
    assert not html_dir(course_id).exists()


# --- serving endpoints ------------------------------------------------------


def _convert_synchronously(client, course_id, monkeypatch, *, extra_css: str = ""):
    monkeypatch.setattr(html_conversion, "_docker_image_present", lambda image: True)
    fake_convert, _ = _fake_convert_factory(extra_css=extra_css)
    monkeypatch.setattr(html_conversion, "_docker_convert", fake_convert)
    _enqueue_convert_html(client, course_id)
    assert run_due_jobs_once() is True


def test_get_asset_html_manifest_404_until_ready(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    resp = client.get(f"/api/assets/{asset_id}/html/manifest")
    assert resp.status_code == 404


def test_get_asset_html_manifest_shape_and_headers_once_ready(client, ingest_course, monkeypatch):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]
    _convert_synchronously(client, course_id, monkeypatch)

    resp = client.get(f"/api/assets/{asset_id}/html/manifest")
    assert resp.status_code == 200
    assert set(resp.json()) == {"pages", "width_px", "height_px"}
    assert resp.json()["pages"] == 12
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert "default-src 'none'" in resp.headers["content-security-policy"]


def test_get_asset_html_page_serves_wrapped_content_with_headers(client, ingest_course, monkeypatch):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]
    _convert_synchronously(client, course_id, monkeypatch)

    resp = client.get(f"/api/assets/{asset_id}/html/1")
    assert resp.status_code == 200
    assert "fake page 1 content" in resp.text
    assert "<style>" in resp.text
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert "style-src 'unsafe-inline'" in resp.headers["content-security-policy"]
    assert "text/html" in resp.headers["content-type"]


def test_get_asset_html_page_404_for_out_of_range_page(client, ingest_course, monkeypatch):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]
    _convert_synchronously(client, course_id, monkeypatch)

    resp = client.get(f"/api/assets/{asset_id}/html/9999")
    assert resp.status_code == 404


def test_get_asset_html_page_404_for_missing_asset(client):
    resp = client.get("/api/assets/does-not-exist/html/1")
    assert resp.status_code == 404


def test_get_asset_html_page_422_for_non_integer_page(client, ingest_course, monkeypatch):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]
    _convert_synchronously(client, course_id, monkeypatch)

    resp = client.get(f"/api/assets/{asset_id}/html/not-a-number")
    assert resp.status_code == 422


def test_resolve_page_path_rejects_paths_outside_the_html_directory(client, ingest_course, monkeypatch, tmp_path):
    """No string input reaches resolve_page_path (page is int-typed at the
    router), but the containment check is still exercised directly here as
    defense in depth, matching every other file-serving endpoint's test
    coverage in this codebase.
    """
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]
    _convert_synchronously(client, course_id, monkeypatch)

    from app.services import html_pages_service

    # Simulate a hypothetically-broken filename builder that produced a
    # path outside the asset's own html directory.
    monkeypatch.setattr(
        html_pages_service,
        "_asset_html_dir",
        lambda asset: tmp_path,  # a directory that does NOT contain page1.html crafted to escape
    )
    # Even pointed at a real, unrelated directory, resolve_page_path should
    # simply 404 (no file there) rather than serve anything unexpected.
    with pytest.raises(html_pages_service.HtmlPageNotFoundError):
        html_pages_service.resolve_page_path(asset_id, 1)


def test_asset_out_exposes_html_status(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    body = client.get(f"/api/courses/{course_id}/assets").json()
    assert body[0]["html_status"] == "none"
