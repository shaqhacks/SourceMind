from __future__ import annotations

import io
import json
import zipfile

import pytest


def test_pdf_locator_serializes_round_trips_and_renders_for_export():
    """Catches losing the structured locator boundary or switching exported
    page ranges away from the API's 1-based user-facing convention.
    """
    from app.pipeline.source_locators import PdfPageLocator, locator_from_dict

    locator = PdfPageLocator(asset_id="asset-123", page_start=0, page_end=3)

    payload = locator.to_dict()
    assert payload == {
        "type": "pdf_pages",
        "asset_id": "asset-123",
        "page_start": 1,
        "page_end": 4,
    }
    assert locator.export_label() == "PDF pages 1-4"
    assert locator_from_dict(payload) == locator


def test_heading_and_chapter_locators_round_trip_without_pdf_pages():
    """Catches assuming every future source locator can be represented as
    page_start/page_end.
    """
    from app.pipeline.source_locators import (
        ChapterFragmentLocator,
        HeadingLocator,
        locator_from_dict,
    )

    heading = HeadingLocator(asset_id="asset-123", heading_path=["Unit 1", "Vocabulary"])
    chapter = ChapterFragmentLocator(asset_id="asset-123", chapter_label="Chapter 2")

    assert locator_from_dict(heading.to_dict()) == heading
    assert locator_from_dict(chapter.to_dict()) == chapter
    assert heading.export_label() == "Unit 1 > Vocabulary"
    assert chapter.export_label() == "Chapter 2"


def test_composite_locator_flattens_round_trips_and_renders_for_export():
    """Catches representing a non-PDF merge as one source heading."""
    from app.pipeline.source_locators import (
        CompositeLocator,
        HeadingLocator,
        locator_from_dict,
    )

    alpha = HeadingLocator(asset_id="asset-123", heading_path=["Alpha"])
    beta = HeadingLocator(asset_id="asset-123", heading_path=["Beta"])
    nested = CompositeLocator.from_locators([alpha, CompositeLocator.from_locators([beta])])

    payload = nested.to_dict()
    assert payload == {
        "type": "composite",
        "asset_id": "asset-123",
        "locators": [
            {"type": "heading", "asset_id": "asset-123", "heading_path": ["Alpha"]},
            {"type": "heading", "asset_id": "asset-123", "heading_path": ["Beta"]},
        ],
    }
    assert nested.export_label() == "Alpha + Beta"
    assert locator_from_dict(payload) == nested


def test_locator_from_dict_rejects_malformed_payloads_with_value_error():
    """Catches malformed stored JSON escaping as AttributeError/RecursionError."""
    from app.pipeline.source_locators import locator_from_dict

    nested = {"type": "heading", "asset_id": "asset-123", "heading_path": ["Leaf"]}
    for _ in range(40):
        nested = {"type": "composite", "asset_id": "asset-123", "locators": [nested]}

    malformed_payloads = [
        "not-a-dict",
        {"type": "composite", "asset_id": "asset-123", "locators": "not-a-list"},
        {"type": "composite", "asset_id": "asset-123", "locators": ["not-a-dict"]},
        nested,
    ]

    for payload in malformed_payloads:
        with pytest.raises(ValueError):
            locator_from_dict(payload)


def test_export_manifest_preserves_structured_pdf_locators(client, ingest_course):
    """Catches exports that keep markdown/assets but drop provenance needed
    to reconstruct where a section came from in the original source.
    """
    course_id, upload_resp, *_ = ingest_course("with_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert sections[0]["source_locator"] == {
        "type": "pdf_pages",
        "asset_id": asset_id,
        "page_start": 1,
        "page_end": 4,
    }

    resp = client.get(f"/api/courses/{course_id}/export")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        first = manifest["sections"][0]
        assert first["source_format"] == "pdf"
        assert first["source_locator"] == sections[0]["source_locator"]
        assert first["source_label"] == "PDF pages 1-4"
