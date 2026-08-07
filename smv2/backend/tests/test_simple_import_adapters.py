from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.config import data_dir

IMPORT_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "imports"


def _create_course(client, title: str = "Simple Import Course") -> str:
    resp = client.post("/api/courses", json={"title": title})
    assert resp.status_code == 201
    return resp.json()["id"]


def _upload(client, course_id: str, filename: str, content: bytes, content_type: str):
    return client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": (filename, content, content_type)},
    )


def _run_ingest(client, course_id: str) -> None:
    from app.jobs.worker import run_due_jobs_once

    ingest = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest.status_code == 202
    assert run_due_jobs_once() is True


def _section_bodies(client, sections: list[dict]) -> list[str]:
    return [
        client.get(f"/api/sections/{section['id']}").json()["body_md"]
        for section in sections
    ]


def _upload_and_ingest(
    client,
    *,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[str, list[dict]]:
    course_id = _create_course(client)
    upload = _upload(client, course_id, filename, content, content_type)
    assert upload.status_code == 201

    _run_ingest(client, course_id)
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    return course_id, sections


def test_markdown_adapter_preserves_headings_code_fences_and_links(client):
    """Catches flattening Markdown through a lossy text parser."""
    markdown = (IMPORT_FIXTURES / "markdown" / "basic.md").read_bytes()

    _course_id, sections = _upload_and_ingest(
        client,
        filename="renamed.bin",
        content=markdown,
        content_type="application/octet-stream",
    )

    assert [section["title"] for section in sections] == ["Course Overview", "Code Sample"]
    joined = "\n\n".join(_section_bodies(client, sections))
    assert "# Course Overview" in joined
    assert "## Code Sample" in joined
    assert "```python\nprint(\"hello\")\n```" in joined
    assert "[SourceMind](https://example.com/source)" in joined
    assert all(section["source_format"] == "markdown" for section in sections)
    assert sections[0]["source_locator"]["heading_path"] == ["Course Overview"]


def test_markdown_adapter_ignores_atx_headings_inside_fenced_code(client):
    """Catches splitting a code sample when it contains heading-shaped text."""
    markdown = b"""# Real Heading

```markdown
# Not A Section
## Also Not A Section
```

After the fenced example.

## Next Real Heading

Actual second section.
"""

    _course_id, sections = _upload_and_ingest(
        client,
        filename="fenced.md",
        content=markdown,
        content_type="text/markdown",
    )

    assert [section["title"] for section in sections] == ["Real Heading", "Next Real Heading"]
    first_body = _section_bodies(client, sections)[0]
    assert "```markdown\n# Not A Section\n## Also Not A Section\n```" in first_body
    assert "After the fenced example." in first_body


def test_text_adapter_splits_paragraphs_with_stable_filename_heading(client):
    """Catches treating plain text as one unstable blob or deriving titles from upload order."""
    text = (IMPORT_FIXTURES / "text" / "basic.txt").read_bytes()

    _course_id, sections = _upload_and_ingest(
        client,
        filename="week 01 notes.data",
        content=text,
        content_type="application/octet-stream",
    )

    assert [section["title"] for section in sections] == [
        "week 01 notes - Paragraph 1",
        "week 01 notes - Paragraph 2",
        "week 01 notes - Paragraph 3",
    ]
    assert _section_bodies(client, sections)[1] == "Second paragraph includes español, 中文, and العربية."
    assert all(section["source_format"] == "text" for section in sections)
    assert sections[1]["source_locator"]["heading_path"] == [
        "week 01 notes",
        "Paragraph 2",
    ]


def test_html_adapter_sanitizes_hostile_html_and_keeps_readable_content(client):
    """Catches retaining executable constructs while converting HTML."""
    html = (IMPORT_FIXTURES / "html" / "malicious.html").read_bytes()

    _course_id, sections = _upload_and_ingest(
        client,
        filename="malicious.txt",
        content=html,
        content_type="text/plain",
    )

    joined = "\n\n".join(_section_bodies(client, sections))
    assert "安全な見出し" in joined
    assert "Keep this text bad link." in joined
    assert "Otro párrafo legible." in joined
    assert "script" not in joined.lower()
    assert "onload" not in joined.lower()
    assert "onclick" not in joined.lower()
    assert "javascript:" not in joined.lower()
    assert all(section["source_format"] == "html" for section in sections)


def test_asset_file_delivery_preserves_hostile_html_bytes_as_attachment(client):
    """Catches serving a hostile original HTML source inline where a browser
    could execute it.
    """
    html = (IMPORT_FIXTURES / "html" / "malicious.html").read_bytes()
    course_id = _create_course(client, "Hostile HTML delivery")
    stored_path = data_dir() / "assets" / course_id / "malicious.html"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(html)

    from app.db.engine import get_session
    from app.db.models import Asset

    session = get_session()
    try:
        asset = Asset(
            course_id=course_id,
            filename='malicious.html\r\nX-Injected: yes\r\n.html',
            content_type="text/html",
            source_format="html",
            media_type="text/html",
            size_bytes=len(html),
            sha256=hashlib.sha256(html).hexdigest(),
            stored_path=str(stored_path),
            status="stored",
        )
        session.add(asset)
        session.commit()
        asset_id = asset.id
    finally:
        session.close()

    response = client.get(f"/api/assets/{asset_id}/file")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]
    assert "x-injected" not in response.headers
    assert "\r" not in response.headers["content-disposition"]
    assert "\n" not in response.headers["content-disposition"]
    assert response.content == html


def test_html_adapter_escapes_entity_decoded_constructs_and_sanitizes_links(client):
    """Catches entity-decoded tag text or hostile hrefs becoming active Markdown/HTML."""
    html = b"""<!doctype html>
<html><body>
  <h1>Escaped Payloads</h1>
  <p>&lt;script&gt;alert(1)&lt;/script&gt; and &lt;img src=x onerror=steal()&gt;</p>
  <!-- hidden comment must not survive -->
  <p><a href="https://example.com/safe?q=1">safe link</a></p>
  <p><a href="javascript:alert(1)">javascript link</a></p>
  <p><a href="data:text/html,boom">data link</a></p>
  <p><a href="https://example.com/a)b\n[Injected](javascript:alert(1))">hostile href punctuation</a></p>
</body></html>
"""

    _course_id, sections = _upload_and_ingest(
        client,
        filename="escaped.html",
        content=html,
        content_type="text/html",
    )

    body = "\n\n".join(_section_bodies(client, sections))
    assert "\\<script\\>alert\\(1\\)\\</script\\>" in body
    assert "\\<img src=x onerror=steal\\(\\)\\>" in body
    assert "hidden comment" not in body
    assert "[safe link](https://example.com/safe?q=1)" in body
    assert "javascript link" in body
    assert "[javascript link]" not in body
    assert "data link" in body
    assert "[data link]" not in body
    assert "[hostile href punctuation]" not in body
    assert "Injected" not in body
    assert "javascript:" not in body.lower()
    assert "data:text/html" not in body.lower()
    assert re.search(r"(?<!\\)<script", body, flags=re.IGNORECASE) is None
    assert re.search(r"(?<!\\)<img", body, flags=re.IGNORECASE) is None


def test_unsupported_upload_returns_stable_415_code(client):
    """Catches returning unstable parser messages for unsupported uploads."""
    course_id = _create_course(client)

    resp = _upload(
        client,
        course_id,
        "archive.zip",
        b"PK\x03\x04unsupported archive body",
        "application/zip",
    )

    assert resp.status_code == 415
    assert resp.json()["detail"] == {"code": "unsupported_source_format"}


def test_archive_container_magic_is_rejected_before_text_fallback(client):
    """Catches ZIP-container bytes being accepted by permissive UTF-8 text sniffing."""
    samples = [
        ("lecture.docx", b"PK\x03\x04docx bytes that are also utf-8", "text/plain"),
        ("slides.pptx", b"PK\x03\x04pptx bytes that are also utf-8", "application/octet-stream"),
        ("book.epub", b"PK\x03\x04epub bytes that are also utf-8", "application/epub+zip"),
        ("archive.txt", b"PK\x03\x04generic zip bytes that are also utf-8", "text/plain"),
        ("empty.zip", b"PK\x05\x06" + (b"\x00" * 18), "text/plain"),
        ("spanned.zip", b"PK\x07\x08zip descriptor bytes that are also utf-8", "text/plain"),
    ]

    for filename, content, content_type in samples:
        course_id = _create_course(client, f"Blocked {filename}")
        resp = _upload(client, course_id, filename, content, content_type)
        assert resp.status_code == 415
        assert resp.json()["detail"] == {"code": "unsupported_source_format"}


def test_simple_formats_are_enabled_without_rollout_flags(client):
    """Catches leaving temporary simple-format rollout flags in the stable path."""
    cases = [
        (
            "notes.md",
            (IMPORT_FIXTURES / "markdown" / "basic.md").read_bytes(),
            "text/markdown",
            "markdown",
        ),
        (
            "notes.txt",
            (IMPORT_FIXTURES / "text" / "basic.txt").read_bytes(),
            "text/plain",
            "text",
        ),
        (
            "notes.html",
            (IMPORT_FIXTURES / "html" / "basic.html").read_bytes(),
            "text/html",
            "html",
        ),
    ]

    for filename, content, content_type, allowed_format in cases:
        course_id = _create_course(client, f"Stable {allowed_format}")
        response = _upload(client, course_id, filename, content, content_type)
        assert response.status_code == 201
        assert response.json()["source_format"] == allowed_format


def test_one_bad_file_does_not_prevent_second_supported_file_from_importing(client):
    """Catches ingest aborting the whole course on a single asset parse failure."""
    from app.db.engine import get_session
    from app.db.models import Asset

    course_id = _create_course(client)
    good = _upload(
        client,
        course_id,
        "notes.txt",
        b"Good paragraph survives.",
        "text/plain",
    )
    assert good.status_code == 201

    bad_content = b"\xff\xfe\x00\x00not valid utf-8"
    bad_path = data_dir() / "assets" / course_id / "broken.md"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_bytes(bad_content)
    session = get_session()
    try:
        bad = Asset(
            course_id=course_id,
            filename="broken.md",
            content_type="text/markdown",
            source_format="markdown",
            media_type="text/markdown",
            size_bytes=len(bad_content),
            sha256=hashlib.sha256(bad_content).hexdigest(),
            stored_path=str(bad_path),
            status="stored",
        )
        session.add(bad)
        session.commit()
        bad_id = bad.id
    finally:
        session.close()

    _run_ingest(client, course_id)

    assets = client.get(f"/api/courses/{course_id}/assets").json()
    by_id = {asset["id"]: asset for asset in assets}
    assert by_id[good.json()["id"]]["status"] == "extracted"
    assert by_id[bad_id]["status"] == "extract_failed"

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert _section_bodies(client, sections) == ["Good paragraph survives."]
