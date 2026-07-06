"""Serves pdf2htmlEX per-page HTML output for an asset's original PDF
(ADR-020). Pages live at data_dir()/assets/{course_id}/html/{asset_id}/,
written by app.pipeline.html_conversion.run_html_conversion — one
page{N}.html per page (already a standalone document, CSS inlined at
conversion time) plus a manifest.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.db.engine import get_session
from app.db.models import Asset
from app.pipeline.html_conversion import html_dir


class AssetNotFoundError(ValueError):
    pass


class HtmlNotReadyError(ValueError):
    pass


class HtmlPageNotFoundError(ValueError):
    pass


def _asset_html_dir(asset: Asset) -> Path:
    return html_dir(asset.course_id) / asset.id


def _get_ready_asset(asset_id: str) -> Asset:
    session = get_session()
    try:
        asset = session.get(Asset, asset_id)
    finally:
        session.close()
    if asset is None:
        raise AssetNotFoundError(f"asset not found: {asset_id!r}")
    if asset.html_status != "ready":
        raise HtmlNotReadyError(
            f"html not ready for asset {asset_id!r} (status={asset.html_status!r})"
        )
    return asset


def get_manifest(asset_id: str) -> dict:
    asset = _get_ready_asset(asset_id)
    manifest_path = _asset_html_dir(asset) / "manifest.json"
    if not manifest_path.is_file():
        raise HtmlNotReadyError(f"manifest missing on disk for asset {asset_id!r}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def resolve_page_path(asset_id: str, page: int) -> Path:
    """page is an int-typed path parameter at the router level (FastAPI
    itself rejects a non-integer value before this is ever called), so
    there's no string/traversal input here the way images_service's
    filename param has — the containment check below is still kept as
    defense in depth, consistent with every other file-serving endpoint
    in this codebase, not because this specific input is untrusted.
    """
    asset = _get_ready_asset(asset_id)
    base_dir = _asset_html_dir(asset).resolve()
    candidate = (base_dir / f"page{page}.html").resolve()
    if candidate != base_dir and base_dir not in candidate.parents:
        raise HtmlPageNotFoundError(f"resolved path escapes the html directory: page={page}")
    if not candidate.is_file():
        raise HtmlPageNotFoundError(f"page {page} not found for asset {asset_id!r}")
    return candidate
