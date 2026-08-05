# Multi-Format Import Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize imports so SourceMind can ingest PDFs, Markdown, plain text, and sanitized HTML through one deterministic pipeline, while keeping DOCX/PPTX/EPUB behind a dependency-review stop gate.

**Architecture:** Insert a format-adapter boundary between asset upload and section extraction so each supported format produces the same normalized source-document shape, including structured locators and extraction warnings. Preserve the current PDF pipeline output exactly, then add simple text-based adapters that do not require new dependencies. Only after a recorded dependency review should archive-based formats be enabled, and even then they must keep the same deterministic, zero-LLM ingest contract and rebuildable derived data.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite, standard-library parsing where possible, Next.js file-upload UI, pytest, Vitest, generated OpenAPI client.

## Global Constraints

- Zero LLM calls during ingest.
- PDF behavior and extraction snapshots must remain stable.
- A failed file must not block other files in the same course.
- Source assets, extracted Markdown, provenance, and locators must remain exportable.
- No new runtime dependency for the first release of the adapter boundary.
- DOCX, PPTX, and EPUB stay blocked until the dependency-review gate is explicitly passed.
- Regenerate `openapi.json` and `frontend/lib/api/schema.d.ts` after backend schema changes.
- `SMV2_IMPORT_MARKDOWN_EXPERIMENTAL`, `SMV2_IMPORT_TEXT_EXPERIMENTAL`, `SMV2_IMPORT_HTML_EXPERIMENTAL`, `SMV2_IMPORT_DOCX_EXPERIMENTAL`, `SMV2_IMPORT_PPTX_EXPERIMENTAL`, and `SMV2_IMPORT_EPUB_EXPERIMENTAL` all start disabled, then move to enabled-by-default only after targeted, full, and manual end-to-end verification, then are removed.

---

### Task 1: Adapter boundary, structured locators, and PDF parity

**Files:**
- Create: `backend/app/db/migrations/versions/0022_source_locators.py`
- Create: `backend/app/pipeline/import_adapters.py`
- Create: `backend/app/pipeline/source_locators.py`
- Create: `backend/tests/test_import_adapter_pdf.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/pipeline/extract.py`
- Modify: `backend/app/pipeline/ingest.py`
- Modify: `backend/app/routers/assets.py`
- Modify: `backend/app/services/assets_service.py`
- Modify: `backend/app/services/export_service.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_asset_upload.py`
- Modify: `backend/tests/test_html_conversion.py`
- Modify: `backend/tests/test_reingest_idempotency.py`

**Interfaces:**
- `DocumentAdapter` protocol with `sniff(asset) -> bool`, `extract(asset) -> NormalizedSourceDocument`, and `format_name` / `format_version` metadata.
- `NormalizedSourceDocument` with `metadata`, `sections`, `warnings`, `failures`, `extractor_name`, `extractor_version`, and `source_format`.
- `NormalizedSection` with `stable_section_id`, `title`, `body_md`, `content_hash`, `source_locator`, `chapter_label`, `asset_id`, and `source_format`.
- `SourceLocator` union values for PDF pages, heading-based documents, slide ranges, and chapter fragments.
- `Section` gains additive locator storage while `page_start` and `page_end` remain populated for PDF compatibility.
- `Asset` records the detected source format so export and file serving stay truthful.
- `resolve_asset_file_path` continues to defend against path traversal, but the file-serving route becomes format-aware instead of hardcoding `application/pdf`.
- If a parser capability is unavailable, startup still falls back to the deterministic supported path instead of failing the app.

- [ ] **Step 1: Write the failing adapter-boundary tests**

Create `backend/tests/test_import_adapter_pdf.py` and `backend/tests/test_source_locators.py` with cases for:
- PDF output staying byte-for-byte stable through the new adapter layer;
- `page_start` and `page_end` still populating for PDF sections;
- structured locators serializing and round-tripping;
- exporter manifest preserving the locator data;
- route/file-serving behavior still rejecting traversal attempts;
- adapter sniffing choosing the PDF adapter for a PDF asset.

Update `backend/tests/test_asset_upload.py` with the first failing expectation that the upload path now preserves enough format metadata to support non-PDF adapters later.

Run:
```bash
cd backend && uv run pytest -q tests/test_import_adapter_pdf.py tests/test_source_locators.py tests/test_asset_upload.py -p no:cacheprovider
```
Expected: fail because the adapter boundary, locator schema, and format-aware serving are not implemented yet.

- [ ] **Step 2: Add the normalized source-document layer**

Implement `backend/app/pipeline/source_locators.py` with concrete dataclasses or Pydantic models for the supported locator shapes, plus deterministic string rendering for export and UI display.

Implement `backend/app/pipeline/import_adapters.py` so the ingest pipeline can choose an adapter by content sniffing rather than filename extension. The first supported adapter remains the existing PDF path, but behind the new interface.

Update `backend/app/pipeline/extract.py` and `backend/app/pipeline/ingest.py` to consume the normalized source-document shape instead of hardcoding PDF-only assumptions at the top of the ingest flow.

Add the migration in `backend/app/db/migrations/versions/0022_source_locators.py` with `down_revision = "0021_search_index"` so the new locator and format metadata are stored durably and can be rederived later.

- [ ] **Step 3: Make the upload and export surfaces format-aware**

Update `backend/app/services/assets_service.py` and `backend/app/routers/assets.py` so the stored asset metadata preserves the original format truthfully and the file-serving route uses the recorded media type instead of assuming PDF.

Update `backend/app/services/export_service.py` to emit the new structured locator data alongside the existing source assets and markdown.

Update `backend/app/schemas.py` and `backend/app/main.py` only as needed to surface the new response fields through OpenAPI.

- [ ] **Step 4: Verify PDF parity and commit**

Run:
```bash
cd backend && uv run pytest -q tests/test_import_adapter_pdf.py tests/test_source_locators.py tests/test_asset_upload.py tests/test_html_conversion.py tests/test_reingest_idempotency.py -p no:cacheprovider
```
Expected: PASS, with the PDF fixtures and existing ingest behavior still unchanged.

Run:
```bash
cd backend && uv run python -m app.export_openapi ../openapi.json
```

Run:
```bash
cd frontend && npm run gen:api
```
Expected: `frontend/lib/api/schema.d.ts` picks up the new source-locator fields after the OpenAPI export.
Expected: `openapi.json` includes the new source-locator fields without regressing existing responses.

Commit only the adapter-boundary and PDF-parity work:
```bash
git add backend/app/db/migrations/versions/0022_source_locators.py backend/app/db/models.py backend/app/main.py backend/app/pipeline/extract.py backend/app/pipeline/import_adapters.py backend/app/pipeline/ingest.py backend/app/pipeline/source_locators.py backend/app/routers/assets.py backend/app/services/assets_service.py backend/app/services/export_service.py backend/app/schemas.py backend/tests/test_source_locators.py backend/tests/test_asset_upload.py backend/tests/test_import_adapter_pdf.py backend/tests/test_html_conversion.py backend/tests/test_reingest_idempotency.py openapi.json frontend/lib/api/schema.d.ts
git commit -m "feat(smv2): add the import adapter boundary"
```

---

### Task 2: Simple format adapters for Markdown, text, and sanitized HTML

**Files:**
- Create: `backend/app/pipeline/html_adapter.py`
- Create: `backend/app/pipeline/markdown_adapter.py`
- Create: `backend/app/pipeline/text_adapter.py`
- Create: `backend/tests/fixtures/imports/html/basic.html`
- Create: `backend/tests/fixtures/imports/html/malicious.html`
- Create: `backend/tests/fixtures/imports/markdown/basic.md`
- Create: `backend/tests/fixtures/imports/text/basic.txt`
- Create: `backend/tests/test_simple_import_adapters.py`
- Modify: `backend/app/pipeline/import_adapters.py`
- Modify: `backend/app/pipeline/ingest.py`
- Modify: `backend/app/services/assets_service.py`
- Modify: `backend/app/services/export_service.py`
- Modify: `backend/tests/test_asset_upload.py`

**Interfaces:**
- `markdown_adapter.extract()` preserves headings, code fences, and inline links without invoking any external parser.
- `text_adapter.extract()` wraps plain text into deterministic sections with a stable heading strategy based on file name and paragraph boundaries.
- `html_adapter.extract()` sanitizes hostile input with a strict allowlist before converting it to Markdown.
- Supported simple formats are Markdown, plain text, and HTML; PDFs still go through the existing extractor path.
- Unsupported input still returns a 415 with a stable error code.
- `SMV2_IMPORT_MARKDOWN_EXPERIMENTAL`, `SMV2_IMPORT_TEXT_EXPERIMENTAL`, and `SMV2_IMPORT_HTML_EXPERIMENTAL` independently gate their adapters and start disabled; PDF remains enabled.

- [ ] **Step 1: Write the failing adapter tests for the simple formats**

Create `backend/tests/test_simple_import_adapters.py` with cases for:
- Markdown preserving headings and code blocks;
- text input being split deterministically into sections;
- HTML sanitization stripping script tags and event handlers;
- hostile HTML still importing readable content;
- non-English text remaining intact;
- unsupported extensions returning 415;
- one bad file not preventing a second supported file from importing.
- each simple-format flag refusing only its own format while disabled and allowing it when enabled.

Run:
```bash
cd backend && uv run pytest -q tests/test_simple_import_adapters.py tests/test_asset_upload.py -p no:cacheprovider
```
Expected: fail because the adapters do not exist yet.

- [ ] **Step 2: Implement the three simple adapters**

Add `backend/app/pipeline/markdown_adapter.py`, `backend/app/pipeline/text_adapter.py`, and `backend/app/pipeline/html_adapter.py` using deterministic parsing only.

Wire each adapter into `backend/app/pipeline/import_adapters.py` so content sniffing selects the correct implementation without relying on filename extension alone.

Register each adapter behind its own rollout flag; do not use one shared switch that can hide which parser caused a rollback.

Update `backend/app/services/assets_service.py` so the upload path preserves the original filename and format metadata for all supported simple formats.

- [ ] **Step 3: Verify the simple formats and commit**

Run:
```bash
cd backend && uv run pytest -q tests/test_simple_import_adapters.py tests/test_asset_upload.py tests/test_import_adapter_pdf.py -p no:cacheprovider
```
Expected: PASS.

Run:
```bash
cd backend && uv run python -m app.export_openapi ../openapi.json
```

Run:
```bash
cd frontend && npm run gen:api
```
Expected: `frontend/lib/api/schema.d.ts` updates after the OpenAPI export.
Expected: PASS, with any new import-related schema fields reflected in the exported schema.

Commit only the simple-format stage:
```bash
git status --short
git add backend/app/pipeline/html_adapter.py backend/app/pipeline/import_adapters.py backend/app/pipeline/markdown_adapter.py backend/app/pipeline/text_adapter.py backend/app/pipeline/ingest.py backend/app/services/assets_service.py backend/app/services/export_service.py backend/tests/fixtures/imports/html/basic.html backend/tests/fixtures/imports/html/malicious.html backend/tests/fixtures/imports/markdown/basic.md backend/tests/fixtures/imports/text/basic.txt backend/tests/test_simple_import_adapters.py backend/tests/test_asset_upload.py openapi.json frontend/lib/api/schema.d.ts
git commit -m "feat(smv2): support simple document import adapters"
```

---

### Task 3: Derived-data invalidation, export fidelity, and reingest safety

**Files:**
- Modify: `backend/app/pipeline/ingest.py`
- Modify: `backend/app/services/export_service.py`
- Modify: `backend/app/services/search_index.py`
- Modify: `backend/tests/test_reingest_idempotency.py`
- Modify: `backend/tests/test_html_conversion.py`
- Modify: `backend/tests/test_asset_upload.py`
- Modify: `backend/tests/test_highlights.py`
- Modify: `backend/tests/test_notes_api.py`
- Modify: `backend/tests/test_search_api.py`
- Create: `backend/tests/test_import_reingest.py`

**Interfaces:**
- Reingest uses the existing full-course, content-addressed section diff as the change boundary: annotations and learner state on surviving section IDs remain intact, while rows owned by removed section IDs are invalidated through their established FK/service paths.
- Course-global generated artifacts without a safe section remap path may still reset, but section-scoped notes, highlights, cards, review state, and progress must not be wiped course-wide.
- Search documents are rebuilt from the post-diff durable rows in the same transaction, including surviving notes and highlights.
- Export preserves original assets, extracted Markdown, source provenance, and structured locators.
- A failed file still marks only that asset failed while the course continues with the rest.
- Reingest remains idempotent and content-addressed for sections that did not change.
- A locator is provenance, not section identity: unchanged sections keep byte-stable locator payloads, while changed content gets a new section ID and the locator produced by its adapter.

- [ ] **Step 1: Write the failing reingest and export tests**

Create `backend/tests/test_import_reingest.py` with cases for:
- section locators surviving a reingest that does not change the source text;
- changed source text getting a new content-addressed section ID and adapter-produced locator while unrelated section IDs and locators remain stable;
- an unchanged section's note and highlight surviving reingest and remaining searchable/exported;
- annotations tied to a removed section disappearing without deleting annotations on surviving sections;
- export including byte-identical original assets, exact section Markdown, and the stored structured locator/provenance metadata;
- one malformed file failing without blocking another file in the same course;
- surviving review state/progress/cards remaining attached to unchanged sections while course-global generated artifacts follow their existing documented reset semantics.

Update `backend/tests/test_reingest_idempotency.py`, `backend/tests/test_html_conversion.py`, and `backend/tests/test_asset_upload.py` to cover the new derived-data expectations.

Run:
```bash
cd backend && uv run pytest -q tests/test_import_reingest.py tests/test_reingest_idempotency.py tests/test_html_conversion.py tests/test_asset_upload.py tests/test_highlights.py tests/test_notes_api.py tests/test_search_api.py -p no:cacheprovider
```
Expected: fail until the invalidation hooks and export changes are in place.

- [ ] **Step 2: Repair the invalidation hooks**

Update `backend/app/pipeline/ingest.py` so the already-computed `existing_sections` versus `new_ids` diff controls section-scoped invalidation. Remove the course-wide note/highlight wipe; stale-mark retained provenance before deleting removed sections; let existing FK/service behavior remove rows owned by deleted sections; update surviving sections in place; rebuild search inputs from the post-diff rows before the single final commit.

Update `backend/app/services/search_index.py` and `backend/app/services/export_service.py` only where tests demonstrate a concrete gap. Do not refactor notes, highlights, lessons, or assets services merely because they were listed in the original draft; they already own CRUD/state behavior rather than locator reconstruction.

Keep the existing REPLACED-on-reingest semantics for unrelated data and do not reset learner state that is tied to unchanged content.

- [ ] **Step 3: Verify the derived-data behavior and commit**

Run:
```bash
cd backend && uv run pytest -q tests/test_import_reingest.py tests/test_reingest_idempotency.py tests/test_html_conversion.py tests/test_asset_upload.py tests/test_highlights.py tests/test_notes_api.py tests/test_search_api.py tests/test_simple_import_adapters.py tests/test_import_adapter_pdf.py -p no:cacheprovider
```
Expected: PASS.

Commit the derived-data stage as its own reviewable unit:
```bash
git add backend/app/pipeline/ingest.py backend/app/services/export_service.py backend/app/services/search_index.py backend/tests/test_import_reingest.py backend/tests/test_reingest_idempotency.py backend/tests/test_html_conversion.py backend/tests/test_asset_upload.py backend/tests/test_highlights.py backend/tests/test_notes_api.py backend/tests/test_search_api.py
git commit -m "feat(smv2): keep import derived data consistent"
```

---

### Task 4: Dependency-review stop gate, archive formats, and rollout

**Files:**
- Create: `backend/app/pipeline/docx_adapter.py`
- Create: `backend/app/pipeline/pptx_adapter.py`
- Create: `backend/app/pipeline/epub_adapter.py`
- Create: `backend/tests/fixtures/imports/docx/basic.docx`
- Create: `backend/tests/fixtures/imports/pptx/basic.pptx`
- Create: `backend/tests/fixtures/imports/epub/basic.epub`
- Create: `backend/tests/test_archive_import_adapters.py`
- Modify if explicitly approved by the recorded dependency decision: `backend/pyproject.toml`
- Modify: `backend/app/pipeline/import_adapters.py`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/test_simple_import_adapters.py`

**Interfaces:**
- `docx_adapter`, `pptx_adapter`, and `epub_adapter` remain blocked until the dependency review is recorded.
- The review must cover maintenance, license, security, extraction fidelity, archive-bomb limits, and deterministic output.
- The archive adapters must enforce file-count, compressed-size, expanded-size, and path-traversal limits before parsing.
- Per-adapter rollback flags keep the archive adapters disabled until each gate is explicitly cleared.
- The DOCX/PPTX/EPUB stage must go red on purpose before implementation after the dependency decision is recorded; do not start adapter code until the failing archive tests prove the gate is still closed.
- `SMV2_IMPORT_DOCX_EXPERIMENTAL`, `SMV2_IMPORT_PPTX_EXPERIMENTAL`, and `SMV2_IMPORT_EPUB_EXPERIMENTAL` are per-adapter rollback flags that start disabled, flip to enabled-by-default only after targeted, full, and manual end-to-end verification, then are removed.

- [ ] **Step 1: Record the dependency-review stop gate before adding any archive parser**

Write the dependency review in the repo's documentation trail and do not touch `backend/pyproject.toml` until the review is explicitly approved.

The review must answer:
- which parser package to add, if any;
- whether each archive format needs a separate dependency or a shared one;
- how the parser behaves on malformed or hostile archives;
- what deterministic fixture corpus proves the adapter output is stable.

Run:
```bash
cd backend && uv run pytest -q tests/test_simple_import_adapters.py tests/test_import_reingest.py tests/test_import_adapter_pdf.py -p no:cacheprovider
```
Expected: PASS before the archive work starts, proving the simple-formats and PDF stages are already stable.

- [ ] **Step 2: Write and run the archive tests after the decision, before adapter implementation**

After the dependency decision is recorded and explicitly approved, create the archive fixture corpus and `backend/tests/test_archive_import_adapters.py` covering valid, malformed, oversized, non-English, image-heavy, traversal, deterministic ordering, and per-adapter disabled/enabled flag cases.

Run:
```bash
cd backend && uv run pytest -q tests/test_archive_import_adapters.py -p no:cacheprovider
```
Expected: FAIL because the approved archive adapters are not implemented yet. A dependency decision by itself is not a GREEN result.

- [ ] **Step 3: Implement the archive adapters only after the review passes and RED is observed**

Add `backend/app/pipeline/docx_adapter.py`, `backend/app/pipeline/pptx_adapter.py`, and `backend/app/pipeline/epub_adapter.py` only after the dependency review approves them, and keep the archive tests red until that approval exists.

Update `backend/app/pipeline/import_adapters.py` to register the archive formats behind the rollout flag from `backend/app/config.py`.

Use the already-red archive fixture corpus and tests to cover:
- valid inputs;
- malformed inputs;
- oversized inputs;
- non-English content;
- image-heavy documents;
- archive traversal attempts;
- deterministic section ordering.

- [ ] **Step 4: Verify the archive stage and commit**

Run:
```bash
cd backend && uv run pytest -q tests/test_archive_import_adapters.py tests/test_simple_import_adapters.py tests/test_import_reingest.py tests/test_import_adapter_pdf.py -p no:cacheprovider
```
Expected: PASS after the dependency-reviewed archive adapters are added.

Run:
```bash
cd backend && uv run python -m app.export_openapi ../openapi.json
```

Run:
```bash
cd frontend && npm run gen:api
```
Expected: `frontend/lib/api/schema.d.ts` updates after the OpenAPI export.
Expected: PASS with no schema drift outside the new locator and format fields.

Commit the archive stage separately from the earlier stages:
```bash
git add backend/app/config.py backend/app/pipeline/docx_adapter.py backend/app/pipeline/epub_adapter.py backend/app/pipeline/import_adapters.py backend/app/pipeline/pptx_adapter.py backend/tests/fixtures/imports/docx/basic.docx backend/tests/fixtures/imports/epub/basic.epub backend/tests/fixtures/imports/pptx/basic.pptx backend/tests/test_archive_import_adapters.py backend/tests/test_simple_import_adapters.py openapi.json frontend/lib/api/schema.d.ts
# Add backend/pyproject.toml and backend/uv.lock only if the approved decision introduced a dependency.
git commit -m "feat(smv2): add archive import adapters after review"
```

---

### Task 5: Final verification and rollout cleanup

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routers/assets.py`
- Modify: `backend/app/pipeline/import_adapters.py`
- Modify: `backend/app/services/assets_service.py`
- Modify: `backend/app/services/export_service.py`
- Modify: `backend/tests/test_asset_upload.py`
- Modify: `backend/tests/test_simple_import_adapters.py`
- Modify: `backend/tests/test_archive_import_adapters.py`

**Interfaces:**
- PDF, Markdown, text, and HTML are the stable default set once the simple-format stage is complete.
- The rollout keeps the per-adapter flags in place only long enough to prove the new formats under targeted, full, and manual end-to-end verification, then removes them.

- [ ] **Step 1: Run the exact verification chain**

Run:
```bash
cd backend && uv run pytest -q tests/test_asset_upload.py tests/test_import_adapter_pdf.py tests/test_simple_import_adapters.py tests/test_import_reingest.py tests/test_archive_import_adapters.py -p no:cacheprovider
```
Expected: PASS.

Run:
```bash
cd backend && uv run python -m app.export_openapi ../openapi.json
```
Expected: PASS.

Run:
```bash
cd frontend && npm run gen:api && npm test -- --run
```
Expected: PASS.

Run:
```bash
./build.sh
```
Expected: PASS end to end.

- [ ] **Step 2: Enable every non-PDF adapter by default and perform the complete manual local smoke**

After changing every implemented non-PDF adapter flag to enabled-by-default, rerun the focused import suite, OpenAPI/client generation, frontend suite, and `./build.sh` from Step 1. Then run `./dev.sh` in a dedicated terminal session. Import one PDF, Markdown, text, HTML, DOCX, PPTX, and EPUB asset from the deterministic fixture corpus. For each format, verify readable ordered sections, the correct locator type, source navigation, export provenance, and unaffected processing of a second valid file when the first file is malformed. Repeat hostile HTML and archive traversal/oversize cases and confirm safe rejection without partial course corruption. Stop the dedicated dev session before any later build or release command.

Expected: every enabled-by-default adapter completes its student journey without a rollback-triggering defect; PDF extraction snapshots remain unchanged.

- [ ] **Step 3: Remove the temporary rollout flags**

Once the targeted/full gates and enabled-by-default manual smoke are green, remove all six per-adapter rollout guards and keep the verified adapters enabled unconditionally.

Commit the cleanup as the final branch commit:
```bash
git add backend/app/config.py backend/app/main.py backend/app/routers/assets.py backend/app/pipeline/import_adapters.py backend/app/services/assets_service.py backend/app/services/export_service.py backend/tests/test_asset_upload.py backend/tests/test_simple_import_adapters.py backend/tests/test_archive_import_adapters.py openapi.json frontend/lib/api/schema.d.ts
git commit -m "chore(smv2): finalize multi-format import rollout"
```
