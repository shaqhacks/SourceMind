# Student Correctness, Review Availability, and Sample Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make review availability and sample-course identity unambiguous across backend and frontend surfaces so new cards are never labeled as overdue and only the seeded sample course can show the sample hint.

**Architecture:** Put review availability behind one backend service that returns explicit `overdue`, `new`, `available`, and `total` counts, then make review, study, and chat consumers derive their copy from that service instead of re-counting rows. Add `Course.is_sample` as the single source of truth for sample hints, backfill it from the existing sample marker on startup, and regenerate the OpenAPI client artifacts so the frontend compiles against the same contract.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite, Pydantic/OpenAPI, Next.js App Router, TypeScript, Vitest, pytest.

## Global Constraints

- Preserve the local-first, single-user architecture.
- Do not add authentication, multi-user sync, or remote settings.
- The backend service is the canonical source for review availability counts; no frontend component may recompute them from raw rows.
- The canonical review counts are `overdue_count`, `new_count`, `available_count`, and `total_count`.
- The sample hint must depend only on `Course.is_sample`; course count, title, and status are not valid heuristics.
- The first-run marker file remains `data_dir()/sample_seeded`; startup reconciliation may read it, but no title-based or count-based migration is allowed.
- Reserve `backend/app/db/migrations/versions/0020_course_is_sample.py` exclusively for this feature; no other migration may claim revision `0020`.
- Regenerate `openapi.json` and `frontend/lib/api/schema.d.ts` after backend schema changes.
- Keep all existing course, review, flashcards, and dashboard routes working during the transition.

---

## File Structure

- Create `backend/app/services/review_availability_service.py`
- Modify `backend/app/db/models.py`
- Modify `backend/app/services/srs_service.py`
- Modify `backend/app/services/study_service.py`
- Modify `backend/app/services/chat_service.py`
- Modify `backend/app/services/sample_service.py`
- Modify `backend/app/schemas.py`
- Modify `backend/tests/test_review.py`
- Modify `backend/tests/test_study_service.py`
- Modify `backend/tests/test_chat.py`
- Modify `backend/tests/test_sample_service.py`
- Modify `backend/tests/test_courses_crud.py`
- Create `backend/tests/test_course_is_sample_migration.py`
- Create `backend/app/db/migrations/versions/0020_course_is_sample.py`
- Modify `openapi.json`
- Modify `frontend/lib/api/schema.d.ts`
- Modify `frontend/app/page.tsx`
- Modify `frontend/components/dashboard/CourseCard.tsx`
- Modify `frontend/components/dashboard/StudyNextList.tsx`
- Modify `frontend/components/DueBadge.tsx`
- Modify `frontend/components/dashboard/StatsRow.tsx`
- Modify `frontend/lib/dashboard/taskCards.ts`
- Modify `frontend/app/review/page.tsx`
- Modify `frontend/app/flashcards/page.tsx`
- Modify `frontend/__tests__/page.test.tsx`
- Modify `frontend/__tests__/course-card.test.tsx`
- Modify `frontend/__tests__/dashboard-task-cards.test.ts`
- Modify `frontend/__tests__/review-page.test.tsx`
- Modify `frontend/__tests__/flashcards-page.test.tsx`
- Create `frontend/__tests__/study-next-list.test.tsx`

## Task 1: Centralize review availability counts

**Files:**
- Create: `backend/app/services/review_availability_service.py`
- Modify: `backend/app/services/srs_service.py`
- Modify: `backend/app/services/study_service.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_review.py`
- Modify: `backend/tests/test_study_service.py`
- Modify: `backend/tests/test_chat.py`
- Create: `backend/tests/test_review_availability_service.py`

**Interfaces:**
- Produces `ReviewAvailability`, a frozen dataclass or Pydantic-style object with `overdue_count`, `new_count`, `available_count`, and `total_count`.
- Produces `get_review_availability(course_id, learner_id, *, now, section_ids=None)` or an equivalent single entry point used everywhere counts are needed.
- Consumes `ReviewState`, `Card`, `CourseLearningProfile`, and the current time only; no consumer may reimplement the joins.
- Study recommendations use `overdue_count` for backlog wording, `new_count` for first-time material, and mixed cases report both counts in the same item detail.
- Chat copy uses the same canonical counts and never describes new cards as overdue.

- [ ] **Step 1: Write the failing backend tests**

Add one focused service test and regressions in the existing surface tests:

- `backend/tests/test_review_availability_service.py` should prove the service returns `overdue_count`, `new_count`, `available_count`, and `total_count` correctly for a mixed course.
- `backend/tests/test_review.py` should assert that the review summary exposes the canonical counts and that the queue still counts only truly overdue cards.
- `backend/tests/test_study_service.py` should assert that a chapter with only new cards is labeled as `new_cards`, a chapter with overdue cards is labeled as `due_cards`, and a mixed chapter reports both counts without describing new cards as due.
- `backend/tests/test_chat.py` should assert that the study-suggestions block says `new` when only new cards exist and says `overdue` when there is a backlog.

Run:

```bash
cd backend && uv run pytest -q tests/test_review_availability_service.py tests/test_review.py tests/test_study_service.py tests/test_chat.py -p no:cacheprovider
```

Expected: FAIL. The new service is missing and the current study/chat copy still conflates new cards with due cards.

- [ ] **Step 2: Implement the canonical count service and wire consumers to it**

Implement the service so it owns the count query once, then delegate these call sites to it:

- `backend/app/services/srs_service.py` should call the service for review summary and review-queue counts instead of recomputing `due` and `new` locally.
- `backend/app/services/study_service.py` should stop treating `new` cards as `due_cards`; it should emit `new_cards` when there is no overdue backlog and mixed detail when both exist.
- `backend/app/services/chat_service.py` should format the learner-state and study-suggestions blocks from the canonical counts and use the words `overdue` and `new` exactly.
- `backend/app/schemas.py` should expose the canonical count names in the response models that power the review summary and study suggestions.

Principal-engineer review gate:

- Reject any implementation that keeps a second count query in a consumer, hard-codes `due` for new cards, or leaves chat copy that suggests new cards are overdue.

- [ ] **Step 3: Verify the count contract on the focused backend surfaces**

Run:

```bash
cd backend && uv run pytest -q tests/test_review_availability_service.py tests/test_review.py tests/test_study_service.py tests/test_chat.py -p no:cacheprovider
```

Expected: PASS. The mixed `0 overdue / 7 new` case should be reported consistently by review summary, study recommendations, and chat.

- [ ] **Step 4: Commit the backend count contract**

Commit boundary:

```bash
git add backend/app/services/review_availability_service.py backend/app/services/srs_service.py backend/app/services/study_service.py backend/app/services/chat_service.py backend/app/schemas.py backend/tests/test_review_availability_service.py backend/tests/test_review.py backend/tests/test_study_service.py backend/tests/test_chat.py
git commit -m "feat(backend): centralize review availability counts"
```

## Task 2: Add explicit sample-course identity

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/db/migrations/versions/0020_course_is_sample.py`
- Modify: `backend/app/services/sample_service.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_sample_service.py`
- Modify: `backend/tests/test_courses_crud.py`
- Create: `backend/tests/test_course_is_sample_migration.py`
- Modify: `openapi.json`
- Modify: `frontend/lib/api/schema.d.ts`

**Interfaces:**
- Produces `Course.is_sample: bool` with a default of `False`.
- Produces a startup reconciliation helper in `sample_service.py` that reads `data_dir()/sample_seeded`, extracts the stored course id, and marks that row as `is_sample=True` if it still exists.
- Keeps the bundled first-run course creation path responsible for setting `is_sample=True` on the new row it creates.
- Exposes `is_sample` through `CourseOut` so the frontend can key the sample hint from data instead of heuristics.
- No database migration may infer sample identity from title, status, or course count.

- [ ] **Step 1: Write failing tests for the explicit sample contract**

Add regressions that make the old heuristic unacceptable:

- `backend/tests/test_sample_service.py` should assert that a marker file pointing at an existing course marks that course as sample on startup reconciliation.
- `backend/tests/test_sample_service.py` should assert that a plain user-created course does not become sample just because it is the only course.
- `backend/tests/test_courses_crud.py` should assert that a newly created course serializes `is_sample=False`.
- `backend/tests/test_course_is_sample_migration.py` should start from an existing `0019_diagnostic_validation` database, seed a course row, upgrade to `0020_course_is_sample`, assert the column exists and untouched rows default to false, then downgrade back to `0019_diagnostic_validation` and assert the original course row still exists after the round-trip.

Run:

```bash
cd backend && uv run pytest -q tests/test_course_is_sample_migration.py tests/test_sample_service.py tests/test_courses_crud.py -p no:cacheprovider
```

Expected: FAIL. The `is_sample` column and reconciliation path do not exist yet.

- [ ] **Step 2: Add the column migration and startup reconciliation**

Implement the migration and runtime backfill in two pieces:

- `backend/app/db/migrations/versions/0020_course_is_sample.py` adds the `is_sample` column with a false default and a not-null constraint.
- `backend/app/db/models.py` adds the mapped field on `Course`.
- `backend/app/services/sample_service.py` adds a reconciliation helper that reads the stored sample marker, finds the referenced course, and marks it as sample without changing any other course.
- `backend/app/schemas.py` includes `is_sample` on `CourseOut`.

Migration behavior:

- The alembic migration only creates the column and its default.
- The startup reconciliation owns the filesystem-dependent backfill because the marker file is not a database artifact.
- The migration regression must prove upgrade and downgrade on an existing DB, not only empty-schema creation.

Principal-engineer review gate:

- Reject any implementation that backfills sample identity from title or status, or that leaves the marker file ignored on existing installs.

- [ ] **Step 3: Regenerate the API artifacts**

Run the committed schema export and client generation steps in this order:

```bash
(cd backend && uv run python -m app.export_openapi ../openapi.json)
(cd frontend && npm run gen:api)
```

Expected: `openapi.json` and `frontend/lib/api/schema.d.ts` change only by adding the `is_sample` field to the course schema and any directly related generated types.

- [ ] **Step 4: Verify the sample contract and commit the backend change**

Run:

```bash
cd backend && uv run pytest -q tests/test_course_is_sample_migration.py tests/test_sample_service.py tests/test_courses_crud.py -p no:cacheprovider
```

Expected: PASS.

Commit boundary:

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/0020_course_is_sample.py backend/app/services/sample_service.py backend/app/schemas.py backend/tests/test_sample_service.py backend/tests/test_courses_crud.py backend/tests/test_course_is_sample_migration.py openapi.json frontend/lib/api/schema.d.ts
git commit -m "feat(backend): mark bundled sample course explicitly"
```

## Task 3: Move all frontend consumers to the explicit contracts

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/components/dashboard/CourseCard.tsx`
- Modify: `frontend/components/dashboard/StudyNextList.tsx`
- Modify: `frontend/components/DueBadge.tsx`
- Modify: `frontend/components/dashboard/StatsRow.tsx`
- Modify: `frontend/lib/dashboard/taskCards.ts`
- Modify: `frontend/app/review/page.tsx`
- Modify: `frontend/app/flashcards/page.tsx`
- Modify: `frontend/__tests__/page.test.tsx`
- Modify: `frontend/__tests__/course-card.test.tsx`
- Modify: `frontend/__tests__/dashboard-task-cards.test.ts`
- Modify: `frontend/__tests__/review-page.test.tsx`
- Modify: `frontend/__tests__/flashcards-page.test.tsx`
- Create: `frontend/__tests__/study-next-list.test.tsx`

**Interfaces:**
- Consumes `course.is_sample` from `CourseOut`.
- Consumes `overdue_count`, `new_count`, `available_count`, and `total_count` from review-summary responses.
- `CourseCard` gets the sample hint treatment, not the page shell, so the hint is attached to the sample course row instead of a course-count heuristic.
- `StudyNextList` must distinguish `overdue` from `new` in its badge text.
- `DueBadge`, `StatsRow`, `taskCards`, `review/page.tsx`, and `flashcards/page.tsx` should all read the canonical overdue/available fields instead of reusing a stale `due_total` naming convention.

- [ ] **Step 1: Write the failing frontend tests**

Add regression coverage where the user-facing strings currently drift:

- `frontend/__tests__/page.test.tsx` should assert that a sole user-created ready course does not show the sample hint, and that a seeded sample course still shows the hint even when other user courses exist.
- `frontend/__tests__/course-card.test.tsx` should assert that a sample course card renders the hint and that dismissing it persists the choice.
- `frontend/__tests__/study-next-list.test.tsx` should assert that `new_cards` renders as new material, `due_cards` renders as overdue material, and mixed detail preserves both counts.
- `frontend/__tests__/review-page.test.tsx`, `frontend/__tests__/flashcards-page.test.tsx`, and `frontend/__tests__/dashboard-task-cards.test.ts` should be updated to the new overdue/available field names so typecheck catches any stale references.

Run:

```bash
cd frontend && npm test -- --run __tests__/page.test.tsx __tests__/course-card.test.tsx __tests__/study-next-list.test.tsx __tests__/dashboard-task-cards.test.tsx __tests__/review-page.test.tsx __tests__/flashcards-page.test.tsx
```

Expected: FAIL. The UI still relies on the old heuristic and old field names.

- [ ] **Step 2: Update the dashboard and review consumers**

Implement the frontend wiring so the new contract is the only path:

- `frontend/app/page.tsx` should stop checking `courses.length` or course titles to decide whether to show the sample hint.
- `frontend/components/dashboard/CourseCard.tsx` should render the sample hint only for `course.is_sample`, not for any ready course chosen by count.
- `frontend/components/DueBadge.tsx`, `frontend/components/dashboard/StatsRow.tsx`, `frontend/lib/dashboard/taskCards.ts`, `frontend/app/review/page.tsx`, and `frontend/app/flashcards/page.tsx` should read the canonical overdue/available count fields.
- `frontend/components/dashboard/StudyNextList.tsx` should show distinct copy for overdue versus new availability and should preserve the mixed-count detail from the backend.

Principal-engineer review gate:

- Reject any implementation that still uses title/count/status heuristics for the sample hint, or any frontend copy that calls new cards overdue.

- [ ] **Step 3: Verify the migrated frontend contract**

Run:

```bash
(cd frontend && npm test -- --run __tests__/page.test.tsx __tests__/course-card.test.tsx __tests__/study-next-list.test.tsx __tests__/dashboard-task-cards.test.tsx __tests__/review-page.test.tsx __tests__/flashcards-page.test.tsx)
(cd frontend && npm run typecheck)
```

Expected: both commands pass.

- [ ] **Step 4: Commit the frontend consumer migration**

Commit boundary:

```bash
git add frontend/app/page.tsx frontend/components/dashboard/CourseCard.tsx frontend/components/dashboard/StudyNextList.tsx frontend/components/DueBadge.tsx frontend/components/dashboard/StatsRow.tsx frontend/lib/dashboard/taskCards.ts frontend/app/review/page.tsx frontend/app/flashcards/page.tsx frontend/__tests__/page.test.tsx frontend/__tests__/course-card.test.tsx frontend/__tests__/dashboard-task-cards.test.tsx frontend/__tests__/review-page.test.tsx frontend/__tests__/flashcards-page.test.tsx frontend/__tests__/study-next-list.test.tsx
git commit -m "feat(frontend): bind sample hint and study copy to canonical counts"
```

## Task 4: Run the full release gate

**Files:**
- Verify only; no new source files are authorized here.

**Interfaces:**
- Consumes the completed backend and frontend changes.
- Produces evidence that the count contract, sample identity, generated schema, and frontend copy all agree.

- [ ] **Step 1: Run the backend regression and schema export**

Run:

```bash
(cd backend && uv run pytest -q tests/test_review_availability_service.py tests/test_review.py tests/test_study_service.py tests/test_chat.py tests/test_course_is_sample_migration.py tests/test_sample_service.py tests/test_courses_crud.py -p no:cacheprovider)
(cd backend && uv run python -m app.export_openapi ../openapi.json)
```

Expected: all backend tests pass and the OpenAPI export succeeds with the new course field and review-summary shapes.

- [ ] **Step 2: Regenerate and verify the frontend schema**

Run:

```bash
(cd frontend && npm run gen:api)
(cd frontend && npm run typecheck)
```

Expected: `frontend/lib/api/schema.d.ts` matches the exported OpenAPI schema and TypeScript passes.

- [ ] **Step 3: Run the focused frontend regression**

Run:

```bash
cd frontend && npm test -- --run __tests__/page.test.tsx __tests__/course-card.test.tsx __tests__/study-next-list.test.tsx __tests__/dashboard-task-cards.test.tsx __tests__/review-page.test.tsx __tests__/flashcards-page.test.tsx
```

Expected: the dashboard, review, flashcards, sample hint, and study-next strings all match the new canonical counts.

- [ ] **Step 4: Run the repository-wide release check**

Run:

```bash
./build.sh
git diff --check
```

Expected: the build exits 0 and there is no whitespace or generated-file drift left behind.

- [ ] **Step 5: Perform the manual local smoke for the student path**

Run:

```bash
./dev.sh
```

Then open the local app in a browser and verify the user path end to end:

- `http://localhost:3000/` shows the sample hint only for the seeded sample course, not for a user-created course.
- `http://localhost:3000/review` reports the same overdue/new split the backend tests covered, and the review summary copy does not call new cards overdue.
- Creating a new ready course and reloading does not make it inherit the sample hint.

Expected: the local smoke matches the automated count contract and false-sample-hint regressions.

Stop the dedicated dev session before any later build or release command; `build.sh` refuses to run while the application ports are occupied.

## Review Gates

- The sample hint must disappear for a sole user-created course and appear for the seeded course regardless of how many other courses exist.
- The review and study surfaces must agree on what is overdue, what is new, and what is available.
- The study-next copy must distinguish overdue backlog from new material.
- No consumer may infer sample identity from title, count, or status after this change.

## Release Notes

- This plan intentionally stages the API schema regeneration before the frontend consumer update.
- If the generated review-summary field names are widened or renamed in a future cleanup, keep the review availability service as the only counting authority.
