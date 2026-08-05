# Task 5C Outline Provenance Repair

## Scope
- Backend only: outline edit provenance repair and focused tests.
- No frontend, schema generation, migration, or dependency changes.

## Changes
- Added `CompositeLocator` for same-asset non-PDF merge provenance, including flattening, roundtrip parsing, and export labels.
- Preserved `asset_id`, `source_format`, `source_locator`, `extractor_version`, `kind`, and `chapter_label` on split/merge rows where applicable.
- Split now requires truthful PDF provenance and writes fresh `pdf_pages` locators for each 0-based DB page range / 1-based API locator range.
- Merge now rejects cross-asset, cross-format, and conflicting extractor provenance; PDF merges produce combined page locators, non-PDF merges produce composite locators.
- `edit_outline` responses now include `source_format` and `source_locator` alongside existing section fields.

## RED Evidence
- `UV_CACHE_DIR=/private/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_source_locators.py tests/test_outline_edit.py -p no:cacheprovider`
- Result before implementation: 8 failed, 11 passed.
- Expected failures covered missing `CompositeLocator`, edit responses dropping locator fields, split/merge losing provenance, and invalid-provenance edits committing.

## GREEN / Verification Evidence
- `UV_CACHE_DIR=/private/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_source_locators.py tests/test_outline_edit.py tests/test_sections_reader.py tests/test_export.py tests/test_import_reingest.py tests/test_import_adapter_pdf.py tests/test_simple_import_adapters.py -p no:cacheprovider`
- Result: 62 passed, 8 warnings.
- `UV_CACHE_DIR=/private/tmp/uv-cache UV_TOOL_DIR=/private/tmp/uv-tools uvx ruff check app/pipeline/source_locators.py app/pipeline/outline.py app/services/outline_service.py tests/test_outline_edit.py tests/test_source_locators.py`
- Result: All checks passed.
- `git diff --check`
- Result: clean.

## Notes
- Warnings are pre-existing environment/library warnings from Starlette/httpx and PyMuPDF/SWIG imports.
- First local `uv run` attempts were environment-blocked by home-directory uv cache access and missing package path; final commands ran from `backend/` with sandbox-local uv cache.
