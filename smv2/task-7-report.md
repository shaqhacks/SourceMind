# Task 7 Report: Unified Flashcard Review E2E

Date: 2026-08-09
HEAD before Task 7 commit: `b9c2868`

## Scope

Task 7 added deterministic Playwright coverage for unified flashcard review:

- course-wide `scope=all`, including a not-due card
- chapter-wide review from the flashcards library
- inline reader grading after answer reveal
- completed-session return to chooser and exact missed-card replay
- failed grade recovery without advancing the card

`task-7-brief.md` was not present in this checkout. The available brief was `docs/superpowers/plans/2026-08-07-unified-flashcard-review.md` plus controller handoff instructions.

## Changes

- Added `frontend/e2e/flashcard-review-scopes.spec.ts`.
- Updated `frontend/__tests__/course-reader.test.tsx` to mock the reader's new `getReviewQueue` dependency and assert the active chapter requests all-card review metadata with `scope: "all"`, exact `chapterLabel`, and `limit: 200`.
- Updated `ultraqa-comprehensive-feature-audit/report.md` with Task 7 evidence.

## Verification

- `rtk npm --prefix frontend run test:e2e -- flashcard-review-scopes.spec.ts --project=chromium -g "completed review returns to chooser and replays exact missed cards"` -> `1 passed`.
- `rtk npm --prefix frontend run test:e2e -- flashcard-review-scopes.spec.ts --project=chromium -g "student grades a revealed card inside the chapter reader"` -> `1 passed`.
- `rtk npm --prefix frontend run test:e2e -- flashcard-review-scopes.spec.ts` -> `10 passed` across Chromium desktop and mobile.
- Backend review suite x3 from `backend/`: `rtk uv run pytest -q tests/test_review.py tests/test_learner_scoping.py tests/test_review_availability_service.py` -> `44 passed, 8 warnings` on each run.
- `rtk npm --prefix frontend run typecheck` -> passed.
- `rtk npm --prefix frontend run lint` -> passed.
- `rtk npm --prefix frontend test -- --run __tests__/course-reader.test.tsx` -> `53 passed`.
- `rtk npm --prefix frontend test -- --run` -> `102 files / 839 tests passed`.
- `rtk ./build.sh` -> backend `884 passed, 31 warnings`; OpenAPI export and generated drift check passed; frontend typecheck passed; frontend Vitest `839 passed`; Next production build passed; `BUILD OK`.

## Notes

- The first build attempt refused to run because a repo-local Next dev server was listening on `:3000`; after confirming it was `frontend/node_modules/.bin/next dev`, it was stopped and the build gate passed.
- The failed-grade E2E intentionally returns one mocked HTTP 503 from `/api/cards/card-due/grade`; the harness asserts exactly one expected browser resource error from that endpoint and still fails on all other console/page errors.
- Generated `frontend/test-results` artifacts were removed before commit.
