from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"


def _create_course(client, title: str = "Upload Test Course") -> str:
    resp = client.post("/api/courses", json={"title": title})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_upload_valid_pdf_creates_asset(client):
    course_id = _create_course(client)
    pdf_path = FIXTURES_DIR / "no_bookmarks.pdf"

    with pdf_path.open("rb") as f:
        resp = client.post(
            f"/api/courses/{course_id}/assets",
            files={"file": ("no_bookmarks.pdf", f, "application/pdf")},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["course_id"] == course_id
    assert body["filename"] == "no_bookmarks.pdf"
    assert body["status"] == "stored"
    assert body["size_bytes"] == pdf_path.stat().st_size
    assert len(body["sha256"]) == 64


def test_upload_rejects_non_pdf_content_by_magic_bytes(client):
    course_id = _create_course(client)

    resp = client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": ("fake.pdf", b"this is not a pdf, just text pretending", "application/pdf")},
    )

    assert resp.status_code == 415


def test_upload_rejects_non_pdf_even_with_pdf_extension_and_content_type(client):
    """Content sniffing, not filename/content-type — a renamed non-PDF must
    still be rejected.
    """
    course_id = _create_course(client)
    resp = client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": ("totally-a.pdf", b"PK\x03\x04not really a pdf", "application/pdf")},
    )
    assert resp.status_code == 415


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setenv("SMV2_MAX_UPLOAD_BYTES", "10")
    course_id = _create_course(client)

    resp = client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": ("small.pdf", b"%PDF-1.7\n" + b"x" * 100, "application/pdf")},
    )

    assert resp.status_code == 413


def test_upload_to_missing_course_is_404(client):
    resp = client.post(
        "/api/courses/does-not-exist/assets",
        files={"file": ("x.pdf", b"%PDF-1.7\nsome content", "application/pdf")},
    )
    assert resp.status_code == 404


def test_upload_rejects_oversized_content_length_without_reading_body(client, monkeypatch):
    """Regression: Content-Length is checked before the body is touched at
    all — a spoofed-large declared size must be rejected immediately,
    without ever invoking the streaming read/validate path (an OOM vector
    otherwise, since a full-body read used to happen before any size check).
    """
    from app.services import assets_service

    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("save_upload must not be called when Content-Length exceeds the cap")

    monkeypatch.setattr(assets_service, "save_upload", _should_not_be_called)

    course_id = _create_course(client)
    resp = client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": ("small.pdf", b"%PDF-1.7 tiny body", "application/pdf")},
        headers={"content-length": "999999999"},
    )
    assert resp.status_code == 413


def test_upload_accepts_pdf_with_leading_junk_before_magic_bytes(client):
    """fitz itself tolerates %PDF- appearing within roughly the first 1KB
    rather than strictly at offset 0 — the upload validator matches that
    same tolerance instead of requiring it at position 0.
    """
    course_id = _create_course(client)
    junk_prefix = b"\x00\x01 some leading junk bytes "
    content = junk_prefix + b"%PDF-1.7\n%comment\n1 0 obj\n<< >>\nendobj\n"

    resp = client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": ("junky.pdf", content, "application/pdf")},
    )
    assert resp.status_code == 201


def test_upload_still_rejects_garbage_with_no_magic_bytes_anywhere(client):
    course_id = _create_course(client)
    resp = client.post(
        f"/api/courses/{course_id}/assets",
        files={
            "file": (
                "garbage.pdf",
                b"just plain garbage, no pdf marker at all here",
                "application/pdf",
            )
        },
    )
    assert resp.status_code == 415


def test_upload_multiple_assets_to_same_course(client):
    course_id = _create_course(client)
    for name in ("with_bookmarks.pdf", "no_bookmarks.pdf"):
        with (FIXTURES_DIR / name).open("rb") as f:
            resp = client.post(
                f"/api/courses/{course_id}/assets",
                files={"file": (name, f, "application/pdf")},
            )
        assert resp.status_code == 201


def test_list_assets_shows_stored_and_extract_failed_with_error_detail(client):
    course_id = _create_course(client)

    with (FIXTURES_DIR / "no_bookmarks.pdf").open("rb") as f:
        stored_resp = client.post(
            f"/api/courses/{course_id}/assets",
            files={"file": ("no_bookmarks.pdf", f, "application/pdf")},
        )
    assert stored_resp.status_code == 201
    stored_id = stored_resp.json()["id"]

    # Seed a second asset directly as extract_failed, simulating a prior
    # failed ingest attempt (e.g. an encrypted/malformed PDF) without
    # re-running the whole pipeline just to get this row into that state.
    from app.db.engine import get_session
    from app.db.models import Asset

    session = get_session()
    try:
        failed_asset = Asset(
            course_id=course_id,
            filename="locked.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            sha256="a" * 64,
            stored_path="/tmp/does-not-exist.pdf",
            status="extract_failed",
            error="PDF is password-protected",
        )
        session.add(failed_asset)
        session.commit()
        failed_id = failed_asset.id
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course_id}/assets")
    assert resp.status_code == 200
    assets = resp.json()
    assert len(assets) == 2

    by_id = {a["id"]: a for a in assets}
    assert by_id[stored_id]["status"] == "stored"
    assert by_id[stored_id]["error"] is None
    assert by_id[failed_id]["status"] == "extract_failed"
    assert by_id[failed_id]["error"] == "PDF is password-protected"


def test_list_assets_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/assets")
    assert resp.status_code == 404


def test_ingest_populates_section_asset_id(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert len(sections) == 3
    assert all(s["asset_id"] == asset_id for s in sections)


def test_section_responses_tolerate_null_asset_id(client, ingest_course):
    """Sections created before this column existed have asset_id=NULL —
    they only backfill on the next re-ingest, never retroactively. Both the
    list and detail responses must serialize fine either way.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    from app.db.engine import get_session
    from app.db.models import Section

    session = get_session()
    try:
        for s in session.query(Section).filter(Section.course_id == course_id).all():
            s.asset_id = None
        session.commit()
    finally:
        session.close()

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert all(s["asset_id"] is None for s in sections)

    detail = client.get(f"/api/sections/{sections[0]['id']}").json()
    assert detail["asset_id"] is None


def test_get_asset_file_serves_exact_bytes_and_content_type(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    resp = client.get(f"/api/assets/{asset_id}/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "inline" in resp.headers["content-disposition"]
    assert resp.content == (FIXTURES_DIR / "with_bookmarks.pdf").read_bytes()


def test_get_asset_file_supports_range_requests(client, ingest_course):
    """pdf.js relies on byte-range requests for progressive loading —
    confirm the installed Starlette FileResponse actually honors Range,
    not just that a full-file GET works.
    """
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]
    full_bytes = (FIXTURES_DIR / "with_bookmarks.pdf").read_bytes()

    resp = client.get(f"/api/assets/{asset_id}/file", headers={"Range": "bytes=0-9"})
    assert resp.status_code == 206
    assert resp.content == full_bytes[:10]
    assert resp.headers["content-range"] == f"bytes 0-9/{len(full_bytes)}"


def test_get_asset_file_404_for_missing_asset(client):
    resp = client.get("/api/assets/does-not-exist/file")
    assert resp.status_code == 404


def test_get_asset_file_404_when_stored_file_missing_on_disk(client, ingest_course):
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    from app.db.engine import get_session
    from app.db.models import Asset

    session = get_session()
    try:
        asset = session.get(Asset, asset_id)
        Path(asset.stored_path).unlink()
    finally:
        session.close()

    resp = client.get(f"/api/assets/{asset_id}/file")
    assert resp.status_code == 404


def test_resolve_asset_file_path_rejects_stored_path_outside_assets_dir(client, ingest_course, tmp_path):
    """stored_path is server-minted (never user input at request time), but
    the containment check must still hold as defense in depth — belt and
    braces, same reasoning as images_service.resolve_image_path.
    """
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    from app.db.engine import get_session
    from app.db.models import Asset

    outside_file = tmp_path / "escaped.pdf"
    outside_file.write_bytes(b"%PDF-1.7\nescaped content")

    session = get_session()
    try:
        asset = session.get(Asset, asset_id)
        asset.stored_path = str(outside_file)
        session.commit()
    finally:
        session.close()

    from app.services import assets_service

    with pytest.raises(assets_service.AssetNotFoundError):
        assets_service.resolve_asset_file_path(asset_id)

    resp = client.get(f"/api/assets/{asset_id}/file")
    assert resp.status_code == 404
