"""pdf2htmlEX per-page HTML conversion — a post-ingest ENHANCEMENT job
(ADR-020), never part of ingest itself: ingest must never slow down or
fail because a Docker-gated feature is unavailable/misbehaving.

pdf2htmlEX's own `--split-pages 1` output is a bare content fragment with
NO surrounding <html>/<head>/<style> — verified empirically while building
this (see ADR-020) — so each page fragment gets wrapped with the
converter's own layout CSS (`--css-filename`, `--embed-css 0`) into a
standalone document before being written to the served directory. Per-
asset isolation: one asset's conversion failing marks only that asset
`html_status='failed'`; the job continues to the next asset.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import fitz
from sqlalchemy.orm import Session

from app.config import data_dir, docker_image
from app.db.models import Asset, Job
from app.pipeline._common import report_progress as _report_progress

logger = logging.getLogger(__name__)

_PAGE_FILENAME_TEMPLATE = "page%d.html"
_CSS_FILENAME = "shared.css"
_PULL_TIMEOUT_SECONDS = 600
_CONVERT_TIMEOUT_SECONDS = 600


class HtmlConversionError(Exception):
    pass


def html_dir(course_id: str) -> Path:
    return data_dir() / "assets" / course_id / "html"


def _docker_image_present(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, timeout=30
    )
    return result.returncode == 0


def _docker_pull(image: str) -> None:
    try:
        result = subprocess.run(
            ["docker", "pull", image], capture_output=True, timeout=_PULL_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise HtmlConversionError(
            f"pulling the pdf2htmlEX converter image {image!r} timed out after "
            f"{_PULL_TIMEOUT_SECONDS}s — check Docker is running and can reach the registry"
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[:500]
        raise HtmlConversionError(
            f"could not pull the pdf2htmlEX converter image {image!r} — check Docker is "
            f"running and can reach the registry: {stderr}"
        )


def _docker_convert(image: str, pdf_path: Path, out_dir: Path) -> None:
    """Runs pdf2htmlEX inside `image`, splitting into one bare content
    fragment per page under out_dir (page1.html, page2.html, ...) plus a
    standalone shared.css with the layout/typography rules those fragments
    need (dimensions, positioning, font metrics) — verified empirically
    that these are the ONLY rules needed for a correct standalone render;
    the converter's OTHER emitted CSS/JS is viewer-chrome (sidebar,
    loading spinner) for its own multi-page reader, irrelevant here since
    each page is served independently.

    Only the single PDF file is bind-mounted (not its whole parent
    directory), so a course with multiple assets never exposes a sibling
    asset's file to the container.
    """
    argv = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{pdf_path}:/in/input.pdf:ro",
        "-v",
        f"{out_dir}:/out",
        image,
        "--split-pages",
        "1",
        "--dest-dir",
        "/out",
        "--page-filename",
        _PAGE_FILENAME_TEMPLATE,
        "--css-filename",
        _CSS_FILENAME,
        "--embed-css",
        "0",
        "--process-outline",
        "0",
        "--embed-outline",
        "0",
        "/in/input.pdf",
        "index.html",
    ]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=_CONVERT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise HtmlConversionError(
            f"pdf2htmlEX timed out after {_CONVERT_TIMEOUT_SECONDS}s"
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[:500]
        raise HtmlConversionError(f"pdf2htmlEX exited {result.returncode}: {stderr}")


def _wrap_page_fragment(fragment: str, css: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8"/><style>'
        f"{css}</style></head><body>{fragment}</body></html>\n"
    )


def _convert_one_asset(asset: Asset, image: str) -> None:
    pdf_path = Path(asset.stored_path)
    doc = fitz.open(str(pdf_path))
    try:
        page_count = doc.page_count
        if page_count <= 0:
            raise HtmlConversionError("PDF has no pages")
        first_page_rect = doc.load_page(0).rect
        # Single width/height pair for the whole asset (not per-page) — a
        # PDF with mixed page sizes (e.g. one landscape page in a portrait
        # book) would have every OTHER page's dimensions misreported by
        # this manifest; not handled here, see ADR-020.
        width_px = round(first_page_rect.width)
        height_px = round(first_page_rect.height)
    finally:
        doc.close()

    with tempfile.TemporaryDirectory() as raw_out:
        raw_out_path = Path(raw_out)
        _docker_convert(image, pdf_path, raw_out_path)

        css_path = raw_out_path / _CSS_FILENAME
        if not css_path.is_file():
            raise HtmlConversionError(f"converter did not produce {_CSS_FILENAME}")
        css = css_path.read_text(encoding="utf-8", errors="replace")

        wrapped_pages: list[str] = []
        for page_num in range(1, page_count + 1):
            fragment_path = raw_out_path / (_PAGE_FILENAME_TEMPLATE % page_num)
            if not fragment_path.is_file():
                raise HtmlConversionError(f"converter did not produce page {page_num}")
            fragment = fragment_path.read_text(encoding="utf-8", errors="replace")
            wrapped_pages.append(_wrap_page_fragment(fragment, css))

        # Only write to the final served directory once every page has been
        # read successfully — a mid-way failure above leaves the asset's
        # existing html/ contents (if any, from a prior successful
        # conversion) untouched rather than half-overwritten.
        final_dir = html_dir(asset.course_id) / asset.id
        if final_dir.exists():
            shutil.rmtree(final_dir)
        final_dir.mkdir(parents=True)
        for page_num, wrapped in enumerate(wrapped_pages, start=1):
            (final_dir / f"page{page_num}.html").write_text(wrapped, encoding="utf-8")
        manifest = {"pages": page_count, "width_px": width_px, "height_px": height_px}
        (final_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def run_html_conversion(session: Session, job: Job, course_id: str) -> dict[str, Any]:
    image = docker_image()
    assets = (
        session.query(Asset)
        .filter(Asset.course_id == course_id)
        .order_by(Asset.created_at.asc())
        .all()
    )
    if not assets:
        return {"course_id": course_id, "converted": 0, "failed": 0}

    _report_progress(
        job.id, stage="starting", pct=0, message=f"converting {len(assets)} asset(s) to HTML"
    )

    if not _docker_image_present(image):
        _report_progress(
            job.id, stage="pulling", pct=0, message="pulling converter image — one-time"
        )
        try:
            _docker_pull(image)
        except HtmlConversionError:
            for asset in assets:
                asset.html_status = "failed"
            session.commit()
            raise

    converted = 0
    failed = 0
    total = len(assets)
    for i, asset in enumerate(assets):
        asset.html_status = "converting"
        session.commit()
        _report_progress(
            job.id,
            stage="converting",
            pct=int(100 * i / total),
            message=f"converting {asset.filename}",
        )
        try:
            _convert_one_asset(asset, image)
        except Exception:
            logger.warning("html conversion failed for asset %s", asset.id, exc_info=True)
            asset.html_status = "failed"
            failed += 1
        else:
            asset.html_status = "ready"
            converted += 1
        session.commit()

    _report_progress(
        job.id, stage="done", pct=100, message=f"converted {converted}/{total} asset(s)"
    )
    return {"course_id": course_id, "converted": converted, "failed": failed}
