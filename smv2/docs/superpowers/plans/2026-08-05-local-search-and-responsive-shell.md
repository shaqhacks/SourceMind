# Local Search and Responsive Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic course search that works fully offline and make the application shell behave correctly from 320px phones through desktop layouts.

**Architecture:** Introduce one course-scoped local search service backed by a contentless SQLite FTS5 index, with a deterministic escaped `LIKE` fallback when FTS5 is unavailable. Expose the service through a new `/api/courses/{course_id}/search` route and a `/search` frontend surface that can be opened from the sidebar, header, and command palette. Rework the app shell into explicit mobile, tablet, and desktop layout bands so navigation, reader chrome, and drawers share one set of breakpoints and focus rules.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite FTS5, Next.js App Router, TypeScript, Vitest, pytest, CSS media queries, generated OpenAPI client.

## Global Constraints

- Search must be deterministic FTS5 with LIKE fallback and never require an LLM or network connection.
- Search excerpts must be sanitized before rendering.
- Layout bands are fixed at 320, 768, 1024, and 1440 CSS pixels.
- The app remains local-first and single-user.
- No new telemetry leaves the machine.
- Regenerate `openapi.json` and `frontend/lib/api/schema.d.ts` after backend schema changes.
- Search-derived rows must rebuild from canonical data after reingest, lesson regeneration, note edits, and note deletion.
- Keyboard focus, Escape dismissal, and route-change dismissal must stay predictable for every drawer or palette.
- `SMV2_FTS_SEARCH_EXPERIMENTAL` and `NEXT_PUBLIC_SMV2_RESPONSIVE_SHELL_EXPERIMENTAL` start disabled, then flip to enabled-by-default only after targeted, full, and manual end-to-end verification, then they are removed.

---

### Task 1: Backend search index, query service, and rebuild command

**Files:**
- Create: `backend/app/db/migrations/versions/0021_search_index.py`
- Create: `backend/app/routers/search.py`
- Create: `backend/app/rebuild_search_index.py`
- Create: `backend/app/services/search_index.py`
- Create: `backend/app/services/search_service.py`
- Create: `backend/tests/test_search_api.py`
- Create: `backend/tests/test_search_service.py`
- Create: `backend/tests/test_search_migration.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/pipeline/ingest.py`
- Modify: `backend/app/services/highlights_service.py`
- Modify: `backend/app/services/lessons_service.py`
- Modify: `backend/app/services/notes_service.py`
- Modify: `frontend/lib/api/schema.d.ts`

**Interfaces:**
- `search_service.search_course(course_id: str, query: str, *, document_types: list[str] | None = None, cursor: str | None = None, limit: int = 20) -> SearchResultsOut`
- `search_service.rebuild_course_index(course_id: str | None = None) -> int`
- `search_index.ensure_search_backend(session) -> Literal["fts5", "like"]`
- `search_index.upsert_section_document(session, section)`, `upsert_lesson_document(session, section)`, `upsert_note_document(session, note)`, `upsert_highlight_document(session, highlight)`, `delete_note_document(session, note_id: str)`, and `delete_highlight_document(session, highlight_id: str)`
- `SearchResultsOut` carries `items`, `next_cursor`, `backend`, and a `sanitized_excerpts` contract for the frontend.
- `SearchResultOut` carries `doc_type`, `course_id`, `section_id`, `asset_id`, `title`, `excerpt_md`, `source_locator`, `score`, and `cursor_token`.
- `SourceLocatorOut` carries structured locator fields for page, heading, chapter, or slide based documents.
- `POST /api/search/rebuild` is not required for end users; the rebuild command is the support path.
- If SQLite starts without FTS5 support, startup and migrations keep the app usable by falling back to deterministic `LIKE` search rather than failing the app or blocking ingest.

- [ ] **Step 1: Write the failing backend tests**

Create `backend/tests/test_search_service.py` with cases for:
- exact-title boost over pure rank;
- query normalization and escaped wildcard handling;
- deterministic ordering across equal scores;
- `cursor` pagination returning no duplicate rows;
- FTS5-backed search when available;
- LIKE fallback when FTS5 is unavailable;
- sanitized excerpts that do not render raw HTML;
- rebuild after reingest, lesson regeneration, note edit, note delete, and highlight delete.

Create `backend/tests/test_search_api.py` with cases for:
- `GET /api/courses/{course_id}/search` returning 200 for a valid query;
- `query=""` returning 422;
- course-scoped results only;
- document-type filtering;
- `next_cursor` round-tripping through the API;
- 404 for a missing course.

Create `backend/tests/test_search_migration.py` with upgrade/downgrade coverage from `0020_course_is_sample` in both capability modes: when FTS5 is available the virtual table is created, and when FTS5 is unavailable the migration and application startup still succeed and select the `LIKE` backend.

Run:
```bash
cd backend && uv run pytest -q tests/test_search_service.py tests/test_search_api.py tests/test_search_migration.py -p no:cacheprovider
```
Expected: fail because the search route, service, and index helpers do not exist yet.

- [ ] **Step 2: Add the search index migration and pure service layer**

Implement `backend/app/db/migrations/versions/0021_search_index.py` with `down_revision = "0020_course_is_sample"`. Its upgrade must probe FTS5 before creating the contentless virtual table; absence of FTS5 is a supported migrated state, not an error. `ensure_search_backend` creates or rebuilds the disposable virtual table later if capability becomes available. Keep canonical data in the existing tables and query those tables for the deterministic `LIKE` fallback.

Implement `backend/app/services/search_index.py` with:
- one probe that decides whether SQLite FTS5 is available;
- one code path for FTS-backed ranking;
- one deterministic `LIKE` fallback that escapes `%`, `_`, and `\` exactly once;
- one rebuild helper that repopulates from `sections`, `lessons`, `notes`, and `highlights`.

Implement `backend/app/services/search_service.py` with:
- pagination and cursor encoding/decoding;
- course-scoped filtering;
- sanitized excerpt assembly;
- stable ranking and tie-breaking;
- rebuild orchestration that can target one course or all courses.

- [ ] **Step 3: Wire the backend route and mutation hooks**

Implement `backend/app/routers/search.py` and include it in `backend/app/main.py`.

Update `backend/app/schemas.py` to export the search response models that the frontend client will consume after OpenAPI regeneration.

Hook the derived-data writers into the same transaction as the source mutation:
- `backend/app/pipeline/ingest.py` invalidates and repopulates section and lesson documents on reingest;
- `backend/app/services/lessons_service.py` refreshes lesson search rows when a lesson is generated or regenerated;
- `backend/app/services/notes_service.py` updates note rows on create/update/delete;
- `backend/app/services/highlights_service.py` updates highlight rows on create/update/delete.

Add `backend/app/rebuild_search_index.py` as the support command wrapper so the index can be rebuilt without starting the web server.

- [ ] **Step 4: Verify the backend behavior and commit**

Run:
```bash
cd backend && uv run pytest -q tests/test_search_service.py tests/test_search_api.py tests/test_search_migration.py -p no:cacheprovider
```
Expected: PASS.

Run:
```bash
cd backend && uv run python -m app.export_openapi ../openapi.json
```
Expected: `openapi.json` changes to include the search response schema and `/api/courses/{course_id}/search`.

Run:
```bash
cd frontend && npm run gen:api
```
Expected: `frontend/lib/api/schema.d.ts` picks up the new search models after the OpenAPI export.

Commit only the backend search artifacts at this point:
```bash
git add backend/app/db/migrations/versions/0021_search_index.py backend/app/main.py backend/app/routers/search.py backend/app/rebuild_search_index.py backend/app/schemas.py backend/app/services/search_index.py backend/app/services/search_service.py backend/app/pipeline/ingest.py backend/app/services/highlights_service.py backend/app/services/lessons_service.py backend/app/services/notes_service.py backend/tests/test_search_api.py backend/tests/test_search_service.py backend/tests/test_search_migration.py openapi.json frontend/lib/api/schema.d.ts
git commit -m "feat(smv2): add deterministic local search backend"
```

---

### Task 2: Frontend search route, command palette, and API client

**Files:**
- Create: `frontend/app/search/page.tsx`
- Create: `frontend/components/search/CommandPalette.tsx`
- Create: `frontend/components/search/CourseSearchClient.tsx`
- Create: `frontend/components/search/SearchBar.tsx`
- Create: `frontend/components/search/SearchResults.tsx`
- Create: `frontend/__tests__/command-palette.test.tsx`
- Create: `frontend/__tests__/search-page.test.tsx`
- Modify: `frontend/components/AppShell.tsx`
- Modify: `frontend/components/AppSidebar.tsx`
- Modify: `frontend/components/SiteHeader.tsx`
- Modify: `frontend/lib/api/client.ts`
- Modify: `frontend/lib/hooks/useKeyboardShortcuts.ts`
- Modify: `frontend/lib/hooks/useNarrowViewport.ts`
- Modify: `frontend/__tests__/app-shell.test.tsx`
- Modify: `frontend/__tests__/site-header.test.tsx`

**Interfaces:**
- `searchCourse(courseId: string, query: string, filters?: { documentTypes?: string[]; cursor?: string | null; limit?: number })`
- `CourseSearchClient` owns the `/search` page state: active course selection, query input, result list, and empty/error states.
- `SearchResults` renders the sanitized excerpts, title, locator, and course navigation link for each hit.
- `CommandPalette` exposes navigation actions and search entry points, and only asks the search service for a course when one is already active.
- `AppSidebar` and `SiteHeader` surface the search route without duplicating the route logic.

- [ ] **Step 1: Write the failing frontend tests**

Create `frontend/__tests__/search-page.test.tsx` with cases for:
- default empty state before a query;
- result rendering with locator and section navigation;
- preserving the course selection across a rerender;
- keyboard submission of the search form;
- empty results copy.

Create `frontend/__tests__/command-palette.test.tsx` with cases for:
- `Ctrl+K` or `Meta+K` opening the palette;
- `Escape` closing it;
- navigation actions for Home, Review, Flashcards, Tests, Jobs, Settings, and Search;
- search action using the active course when present.

Update `frontend/__tests__/site-header.test.tsx` and `frontend/__tests__/app-shell.test.tsx` to cover the new search affordance and to prove the shell still mounts the correct top-level surfaces.

Run:
```bash
cd frontend && npm test -- --run __tests__/search-page.test.tsx __tests__/command-palette.test.tsx __tests__/site-header.test.tsx __tests__/app-shell.test.tsx
```
Expected: fail because the search page, palette, and client helper do not exist yet.

- [ ] **Step 2: Add the generated client surface and page**

Update `frontend/lib/api/client.ts` with the typed search helper that matches the regenerated schema from Task 1.

Create `frontend/app/search/page.tsx` as a client-facing course search page that:
- loads the course list;
- lets the user choose the active course;
- queries the backend search route;
- routes clicks back into the reader at the correct section and locator.

Create `frontend/components/search/CourseSearchClient.tsx`, `SearchBar.tsx`, and `SearchResults.tsx` so the page stays focused, testable, and accessible.

- [ ] **Step 3: Add the command palette and shell entry points**

Create `frontend/components/search/CommandPalette.tsx` and wire it into `SiteHeader`.

Add `Search` to the primary navigation in `AppSidebar` and ensure the header and sidebar both navigate to the same `/search` route instead of creating duplicate search logic.

Keep `AppShell` as the single shell owner so the new page still inherits the existing viewport-bounded scroll behavior and skip-link contract.

- [ ] **Step 4: Verify the frontend behavior, regenerate the client, and commit**

Run:
```bash
cd frontend && npm run gen:api
```
Expected: `frontend/lib/api/schema.d.ts` includes the search route and result schemas.

Run:
```bash
cd frontend && npm test -- --run __tests__/search-page.test.tsx __tests__/command-palette.test.tsx __tests__/site-header.test.tsx __tests__/app-shell.test.tsx
```
Expected: PASS.

Commit only the frontend search artifacts at this point:
```bash
git add frontend/app/search/page.tsx frontend/components/search/CommandPalette.tsx frontend/components/search/CourseSearchClient.tsx frontend/components/search/SearchBar.tsx frontend/components/search/SearchResults.tsx frontend/components/AppShell.tsx frontend/components/AppSidebar.tsx frontend/components/SiteHeader.tsx frontend/lib/api/client.ts frontend/lib/hooks/useKeyboardShortcuts.ts frontend/lib/hooks/useNarrowViewport.ts frontend/__tests__/command-palette.test.tsx frontend/__tests__/search-page.test.tsx frontend/__tests__/app-shell.test.tsx frontend/__tests__/site-header.test.tsx frontend/lib/api/schema.d.ts
git commit -m "feat(smv2): add local search frontend"
```

---

### Task 3: Responsive shell, drawers, and mobile-first layout bands

**Files:**
- Create: `frontend/lib/hooks/useShellLayout.ts`
- Create: `frontend/__tests__/responsive-shell.test.tsx`
- Modify: `frontend/app/globals.css`
- Modify: `frontend/components/AppShell.tsx`
- Modify: `frontend/components/AppSidebar.tsx`
- Modify: `frontend/components/SiteHeader.tsx`
- Modify: `frontend/components/reader/CourseReader.tsx`
- Modify: `frontend/components/reader/CourseChatDrawer.tsx`
- Modify: `frontend/components/reader/ReadingColumn.tsx`
- Modify: `frontend/components/reader/Sidebar.tsx`
- Modify: `frontend/components/reader/TopBar.tsx`
- Modify: `frontend/lib/hooks/useNarrowViewport.ts`
- Modify: `frontend/__tests__/app-shell.test.tsx`
- Modify: `frontend/__tests__/reader-topbar.test.tsx`
- Modify: `frontend/__tests__/course-reader.test.tsx`

**Interfaces:**
- `useShellLayout()` returns one of `mobile`, `tablet`, or `desktop` based on the 320/768/1024/1440 layout bands.
- `AppShell` decides whether the sidebar is persistent, drawer-based, or hidden behind a compact trigger.
- `SiteHeader` owns the compact mobile header controls and the focusable nav toggle.
- Reader drawers trap focus, close on Escape or route change, and restore focus to the trigger.

- [ ] **Step 1: Write the failing responsive-shell tests**

Create `frontend/__tests__/responsive-shell.test.tsx` with cases for:
- 320px rendering a compact header and overlay navigation;
- 768px rendering a tablet drawer instead of a persistent sidebar;
- 1024px rendering the desktop sidebar;
- 1440px preserving the same desktop structure without horizontal overflow;
- focus restoration after drawer close.

Update `frontend/__tests__/reader-topbar.test.tsx` and `frontend/__tests__/course-reader.test.tsx` to cover the reader chrome behavior at the new breakpoints.

Run:
```bash
cd frontend && npm test -- --run __tests__/responsive-shell.test.tsx __tests__/reader-topbar.test.tsx __tests__/course-reader.test.tsx __tests__/app-shell.test.tsx
```
Expected: fail because the new layout bands and drawer behavior are not wired up yet.

- [ ] **Step 2: Implement the shared breakpoint logic and CSS bands**

Add `frontend/lib/hooks/useShellLayout.ts` so the shell and reader chrome can share one breakpoint definition instead of duplicating media-query math.

Update `frontend/app/globals.css` with explicit layout bands for 320, 768, 1024, and 1440 CSS pixels, including drawer transitions, overflow rules, and minimum touch-target sizing for nav controls.

Refactor `AppShell`, `AppSidebar`, `SiteHeader`, `CourseReader`, `TopBar`, `Sidebar`, `ReadingColumn`, and `CourseChatDrawer` so the responsive behavior is driven by layout mode rather than by ad hoc class toggles.

- [ ] **Step 3: Verify accessibility and interaction behavior**

Confirm the following in the updated tests:
- drawers trap focus while open;
- Escape closes the topmost drawer or palette;
- route changes close transient overlays;
- the skip-to-main link still lands on `main#main-content`;
- no layout band introduces horizontal scrolling at 320, 768, 1024, or 1440 pixels.

- [ ] **Step 4: Run the full frontend gate and commit**

Run:
```bash
cd frontend && npm test -- --run __tests__/responsive-shell.test.tsx __tests__/reader-topbar.test.tsx __tests__/course-reader.test.tsx __tests__/app-shell.test.tsx __tests__/site-header.test.tsx __tests__/search-page.test.tsx __tests__/command-palette.test.tsx
```
Expected: PASS.

Run:
```bash
cd frontend && npm run typecheck && npm run build
```
Expected: PASS.

Commit the responsive-shell changes separately so the layout work can be reviewed independently from the search feature:
```bash
git add frontend/app/globals.css frontend/components/AppShell.tsx frontend/components/AppSidebar.tsx frontend/components/SiteHeader.tsx frontend/components/reader/CourseReader.tsx frontend/components/reader/CourseChatDrawer.tsx frontend/components/reader/ReadingColumn.tsx frontend/components/reader/Sidebar.tsx frontend/components/reader/TopBar.tsx frontend/lib/hooks/useNarrowViewport.ts frontend/lib/hooks/useShellLayout.ts frontend/__tests__/responsive-shell.test.tsx frontend/__tests__/app-shell.test.tsx frontend/__tests__/reader-topbar.test.tsx frontend/__tests__/course-reader.test.tsx
git commit -m "feat(smv2): make the shell responsive across layouts"
```

---

### Task 4: Release gating, rollout, and end-to-end verification

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/routers/search.py`
- Modify: `backend/app/main.py`
- Modify: `frontend/app/search/page.tsx`
- Modify: `frontend/components/AppSidebar.tsx`
- Modify: `frontend/components/SiteHeader.tsx`
- Modify: `frontend/components/search/CommandPalette.tsx`
- Modify: `frontend/components/search/CourseSearchClient.tsx`
- Modify: `frontend/__tests__/command-palette.test.tsx`
- Modify: `frontend/__tests__/search-page.test.tsx`

**Interfaces:**
- `SMV2_FTS_SEARCH_EXPERIMENTAL` gates the backend FTS-backed ranking path and starts disabled; the search API remains usable through `LIKE` fallback.
- `NEXT_PUBLIC_SMV2_RESPONSIVE_SHELL_EXPERIMENTAL` gates the frontend responsive shell replacement and starts disabled.
- Both flags stay off until the targeted and full gates pass. They are then enabled by default for the complete manual smoke and removed only if that smoke has no rollback-triggering defect.

- [ ] **Step 1: Add the rollout flag and wire the temporary guards**

Add the backend FTS flag in `backend/app/config.py` and the frontend responsive-shell flag at the shell boundary. Do not hide the deterministic search API or Search navigation merely because FTS ranking is disabled; the `LIKE` backend is the supported fallback.

- [ ] **Step 2: Run the exact verification chain**

Run:
```bash
cd backend && uv run pytest -q tests/test_search_service.py tests/test_search_api.py tests/test_asset_upload.py tests/test_sample_service.py -p no:cacheprovider
```
Expected: PASS.

Run:
```bash
cd backend && uv run python -m app.export_openapi ../openapi.json
```
Expected: PASS with a clean OpenAPI diff after the search route is added.

Run:
```bash
cd frontend && npm run gen:api && npm test -- --run __tests__/search-page.test.tsx __tests__/command-palette.test.tsx __tests__/responsive-shell.test.tsx __tests__/app-shell.test.tsx __tests__/site-header.test.tsx __tests__/reader-topbar.test.tsx __tests__/course-reader.test.tsx && npm run typecheck && npm run build
```
Expected: PASS.

Run:
```bash
./build.sh
```
Expected: PASS end to end.

- [ ] **Step 3: Enable both flags by default and perform the complete manual local smoke**

After changing both flags to enabled-by-default, rerun the focused backend search tests, focused frontend search/responsive tests, typecheck, frontend build, and `./build.sh` from Step 2. Then run `./dev.sh` in a dedicated terminal session and verify with a large local course that source, lesson, note, and highlight queries navigate to the correct section; rebuild the search index and repeat; verify the same query under forced `LIKE` fallback; and inspect dashboard, reader, review, flashcards, tests, upload, Jobs, and Settings at 320, 768, 1024, and 1440 CSS pixels. At every width, verify no unintended horizontal overflow and confirm drawer focus trap, Escape close, route-change close, and trigger focus restoration. Stop the dedicated dev session before any later build or release command.

Expected: the enabled-by-default FTS path and responsive replacement complete the full student journey without a rollback-triggering defect.

- [ ] **Step 4: Remove the temporary rollout guards and finalize the branch**

Once the automated gates and enabled-by-default manual smoke are green, remove `SMV2_FTS_SEARCH_EXPERIMENTAL` and `NEXT_PUBLIC_SMV2_RESPONSIVE_SHELL_EXPERIMENTAL` and keep the verified production behavior.

Commit the rollout cleanup as its own final commit so the temporary gate does not linger in mainline:
```bash
git add backend/app/config.py backend/app/main.py backend/app/routers/search.py frontend/app/search/page.tsx frontend/components/AppSidebar.tsx frontend/components/SiteHeader.tsx frontend/components/search/CommandPalette.tsx frontend/components/search/CourseSearchClient.tsx frontend/__tests__/command-palette.test.tsx frontend/__tests__/search-page.test.tsx openapi.json frontend/lib/api/schema.d.ts
git commit -m "chore(smv2): finalize local search rollout"
```
