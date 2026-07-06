from __future__ import annotations

import io
import json
import zipfile


def test_export_zip_structure_and_content(client, ingest_course, tmp_path):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    resp = client.get(f"/api/courses/{course_id}/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zip_path = tmp_path / "export.zip"
    zip_path.write_bytes(resp.content)

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "outline.md" in names
        assert "manifest.json" in names
        assert any(n.startswith("assets/") and n.endswith(".pdf") for n in names)

        section_files = [n for n in names if n not in {"outline.md", "manifest.json"} and not n.startswith("assets/")]
        assert len(section_files) == 3

        outline_text = zf.read("outline.md").decode("utf-8")
        assert "Chapter 1: Foundations" in outline_text
        assert "Chapter 2: Structures" in outline_text
        assert "Chapter 3: Applications" in outline_text

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["course"]["id"] == course_id
        assert len(manifest["sections"]) == 3
        assert all("content_hash" in s for s in manifest["sections"])
        assert all("extractor_version" in s for s in manifest["sections"])

        first_section_file = sorted(section_files)[0]
        section_content = zf.read(first_section_file).decode("utf-8")
        assert "Chapter 1: Foundations" in section_content


def test_export_zip_is_a_valid_zip_readable_via_bytesio(client, ingest_course):
    course_id, *_ = ingest_course("no_bookmarks.pdf")
    resp = client.get(f"/api/courses/{course_id}/export")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        bad_file = zf.testzip()
        assert bad_file is None


def test_export_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/export")
    assert resp.status_code == 404


def test_export_includes_lesson_file_and_manifest_entry_when_ready(client, ingest_course, stub_provider):
    """Lessons are paid-for, generated content — omitting them from the
    export silently held the reader's content hostage to the app, contrary
    to the brief's law that a user can always get their own content out.
    """
    from app.jobs.worker import run_due_jobs_once
    from app.llm.provider import CompletionResult
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(text="A real lesson.", input_tokens=1, output_tokens=1, model="stub-model")
    ]
    client.post(f"/api/sections/{section_id}/lesson")
    assert run_due_jobs_once() is True

    resp = client.get(f"/api/courses/{course_id}/export")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        lesson_files = [n for n in names if n.startswith("lessons/") and n.endswith(".lesson.md")]
        assert len(lesson_files) == 1

        content = zf.read(lesson_files[0]).decode("utf-8")
        assert "stub-model" in content
        assert "v2" in content
        assert "A real lesson." in content

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        section_entry = next(s for s in manifest["sections"] if s["id"] == section_id)
        assert section_entry["lesson"]["status"] == "ready"
        assert section_entry["lesson"]["model"] == "stub-model"
        assert section_entry["lesson"]["prompt_version"] == "v2"
        assert section_entry["lesson"]["file"] == lesson_files[0]

        # Sections with no lesson yet must have a null manifest entry, not a
        # missing key or a stale/wrong status.
        other_entries = [s for s in manifest["sections"] if s["id"] != section_id]
        assert all(s["lesson"] is None for s in other_entries)


def test_export_unchanged_for_course_with_no_lessons(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    resp = client.get(f"/api/courses/{course_id}/export")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        assert not any(n.startswith("lessons/") for n in names)

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert all(s["lesson"] is None for s in manifest["sections"])
