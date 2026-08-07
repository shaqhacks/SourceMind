# Unified Flashcard Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let students grade cards consistently wherever they encounter them, review every generated card for a course or chapter on demand, and reliably return to or replay a completed review session.

**Architecture:** Extend the existing course review queue with explicit scopes while preserving the current due/new default. Add one order-preserving card-selection endpoint for replaying a completed session’s exact missed cards. Centralize grade controls and session persistence in small frontend modules, then reuse those contracts in the review route, flashcards library, and reader without replacing the deterministic scheduler.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, pytest, Next.js 16, React 19, TypeScript, Vitest, Playwright.

## Global Constraints

- `available` remains the default queue scope and retains current due/new behavior.
- `all` includes new, due, and not-due cards for the selected course or chapter.
- `needs_attention` means the learner’s latest persisted grade for the card is `Again` (`ReviewState.last_grade == 1`).
- “Review missed” means the exact card IDs graded `Again` in the just-completed session, not every historical `Again` card.
- A completed-session snapshot expires after 24 hours and contains no card content.
- The server remains authoritative for card ownership, scheduler state, and grading.
- Course and learner scoping must prevent cross-course selection and cross-learner review-state leakage.
- Existing keyboard shortcuts (`space`, `1`–`4`) and interval previews remain available.
- Grade submission must expose pending and error states; do not silently discard a failed grade.
- Maximum queue and explicit-selection size stays 200 cards.
- No new runtime dependency is required.
- Every shell command in this workspace is prefixed with `rtk`.

---

## File Structure

- Create `frontend/components/review/ReviewGradeControls.tsx`: shared Again/Hard/Good/Easy controls with interval previews.
- Create `frontend/lib/review/sessionStorage.ts`: versioned active/completed session persistence with a 24-hour completed-session TTL.
- Create `frontend/lib/review/gradeCardAndNotify.ts`: checked grade submission plus review-bus notification.
- Create `frontend/e2e/flashcard-review-scopes.spec.ts`: course, chapter, inline grading, completion navigation, and missed replay coverage.
- Modify the existing review API, flashcard surfaces, reader, generated API artifacts, and tests listed per task below.

### Task 1: Add Backward-Compatible Review Scopes

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/srs_service.py`
- Modify: `backend/app/routers/review.py`
- Modify: `backend/tests/test_review.py`
- Modify: `backend/tests/test_learner_scoping.py`

**Interfaces:**
- Produces query parameters `scope: Literal["available", "all", "needs_attention"] = "available"` and `chapter_label: str | None = None` on `GET /api/courses/{course_id}/review/queue`.
- Extends `ReviewQueueCardOut` with `chapter_label: str | None`, `section_title: str`, `is_due: bool`, and `last_grade: int | None`.
- Keeps all existing count fields course-wide and unchanged; `cards.length` is the selected scope count.

- [ ] **Step 1: Write failing service and API tests**

Add fixtures containing new, due, future-due, latest-Again, latest-Good, and second-chapter cards. Assert:

```python
def test_review_queue_defaults_to_available_cards(client, review_course):
    response = client.get(f"/api/courses/{review_course.id}/review/queue")
    assert response.status_code == 200
    assert set(card["id"] for card in response.json()["cards"]) == review_course.available_ids


def test_review_queue_all_scope_includes_not_due_cards(client, review_course):
    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "all", "limit": 200},
    )
    assert [card["id"] for card in response.json()["cards"]] == review_course.all_ids


def test_review_queue_needs_attention_uses_latest_again_state(client, review_course):
    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "needs_attention"},
    )
    assert [card["id"] for card in response.json()["cards"]] == review_course.latest_again_ids


def test_review_queue_filters_by_exact_chapter_label(client, review_course):
    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "all", "chapter_label": "Chapter 2"},
    )
    assert {card["chapter_label"] for card in response.json()["cards"]} == {"Chapter 2"}
```

Add learner-scoping assertions proving another learner’s `Again` state does not place the same shared card in the current learner’s `needs_attention` queue. Add a 422 assertion for an unknown scope.

- [ ] **Step 2: Run focused tests and confirm failure**

```bash
rtk uv run pytest -q backend/tests/test_review.py backend/tests/test_learner_scoping.py -k 'scope or chapter_label or needs_attention'
```

Expected: FAIL because the queue has no scope or chapter metadata.

- [ ] **Step 3: Implement one scoped query path**

Refactor `get_review_queue()` to join `Section` once and apply these predicates:

| Scope | Predicate |
| --- | --- |
| `available` | no learner `ReviewState`, or `due_at <= now` |
| `all` | no due-date predicate |
| `needs_attention` | learner `ReviewState.last_grade == AGAIN` |

Apply `Section.chapter_label == chapter_label` only when the query parameter is present. Preserve the existing stable order by `coalesce(ReviewState.due_at, Card.created_at)`, then `Card.created_at`, then `Card.id`. Return `section.title` and `section.chapter_label` with every card. Set `is_due` only when a learner state exists and its due date is at or before the query timestamp; new cards remain `is_new=True, is_due=False`. Return the learner state’s `last_grade`, or null for new cards. Do not change `get_review_availability()` or dashboard counts.

- [ ] **Step 4: Run the review regression suite**

```bash
rtk uv run pytest -q backend/tests/test_review.py backend/tests/test_learner_scoping.py backend/tests/test_review_availability_service.py
```

Expected: PASS, including all pre-existing default-queue assertions.

- [ ] **Step 5: Commit scoped queues**

```bash
rtk git add backend/app/schemas.py backend/app/services/srs_service.py backend/app/routers/review.py backend/tests/test_review.py backend/tests/test_learner_scoping.py
rtk git commit -m "feat(review): add course and chapter card scopes"
```

### Task 2: Add Exact Card Selection for Completed-Session Replay

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/srs_service.py`
- Modify: `backend/app/routers/review.py`
- Modify: `backend/tests/test_review.py`
- Modify: `backend/tests/test_learner_scoping.py`

**Interfaces:**
- Produces `ReviewSelectionIn(card_ids: list[str])` with 1–200 unique IDs.
- Produces `ReviewSelectionOut(cards: list[ReviewQueueCardOut], missing_card_ids: list[str])`.
- Produces `POST /api/courses/{course_id}/review/selection`.
- Preserves requested order and returns deleted or wrong-course IDs in `missing_card_ids` without leaking their metadata.

- [ ] **Step 1: Write failing selection tests**

```python
def test_review_selection_preserves_requested_order_and_includes_not_due(client, review_course):
    requested = [review_course.future_id, review_course.new_id, review_course.due_id]
    response = client.post(
        f"/api/courses/{review_course.id}/review/selection",
        json={"card_ids": requested},
    )
    assert response.status_code == 200
    assert [card["id"] for card in response.json()["cards"]] == requested
    assert response.json()["missing_card_ids"] == []


def test_review_selection_reports_wrong_course_id_without_metadata(client, review_course, other_course):
    response = client.post(
        f"/api/courses/{review_course.id}/review/selection",
        json={"card_ids": [review_course.due_id, other_course.card_id, "deleted-card"]},
    )
    assert [card["id"] for card in response.json()["cards"]] == [review_course.due_id]
    assert response.json()["missing_card_ids"] == [other_course.card_id, "deleted-card"]
```

Add validation tests for an empty list, duplicate IDs, and more than 200 IDs. Add a learner test proving the returned scheduler fields come from the requesting learner’s profile.

- [ ] **Step 2: Run focused tests and confirm failure**

```bash
rtk uv run pytest -q backend/tests/test_review.py backend/tests/test_learner_scoping.py -k selection
```

Expected: FAIL because the endpoint and schemas do not exist.

- [ ] **Step 3: Implement order-preserving selection**

Load cards with `Card.course_id == course_id`, join the requesting learner’s `ReviewState`, build a dictionary keyed by card ID, and reconstruct `cards` in request order. Never query or return metadata for IDs outside the selected course. Reuse the same card serializer as Task 1 so interval previews remain identical across queue and selection responses.

- [ ] **Step 4: Run backend review tests**

```bash
rtk uv run pytest -q backend/tests/test_review.py backend/tests/test_learner_scoping.py
```

Expected: PASS with no scheduler behavior changes.

- [ ] **Step 5: Commit exact selection**

```bash
rtk git add backend/app/schemas.py backend/app/services/srs_service.py backend/app/routers/review.py backend/tests/test_review.py backend/tests/test_learner_scoping.py
rtk git commit -m "feat(review): replay exact card selections"
```

### Task 3: Generate the Client Contract and Centralize Grade Submission

**Files:**
- Modify: `openapi.json`
- Modify: `frontend/lib/api/schema.d.ts`
- Modify: `frontend/lib/api/client.ts`
- Modify: `frontend/app/review/page.tsx`
- Modify: `frontend/components/flashcards/FlashcardsClient.tsx`
- Create: `frontend/lib/review/gradeCardAndNotify.ts`
- Create: `frontend/components/review/ReviewGradeControls.tsx`
- Create: `frontend/__tests__/review-grade-controls.test.tsx`
- Create: `frontend/__tests__/api-client.test.ts`

**Interfaces:**
- Produces `getReviewQueue(courseId, { limit, scope, chapterLabel })`.
- Produces `getReviewSelection(courseId, cardIds)`.
- Produces `gradeCardAndNotify(cardId, grade, elapsedMs)` returning a checked `ApiResult<GradeCardOut>`.
- Produces `ReviewGradeControls` with grades, interval previews, disabled/pending state, and an accessible error slot.

- [ ] **Step 1: Write failing client and component tests**

```tsx
it("submits the selected grade once and disables every grade while pending", async () => {
  const request = deferredGradeResponse();
  mockGradeCardAndNotify.mockReturnValue(request.promise);
  render(<ReviewGradeControls card={reviewCard()} onGraded={onGraded} />);
  await user.click(screen.getByRole("button", { name: /good/i }));
  expect(mockGradeCardAndNotify).toHaveBeenCalledWith("card-1", 3, expect.any(Number));
  for (const button of screen.getAllByRole("button")) {
    expect(button).toBeDisabled();
  }
  request.resolve(successfulGradeResult());
});

it("keeps controls available and announces a failed grade", async () => {
  mockGradeCardAndNotify.mockResolvedValue(failedGradeResult(503));
  render(<ReviewGradeControls card={reviewCard()} onGraded={onGraded} />);
  await user.click(screen.getByRole("button", { name: /again/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/could not save/i);
  expect(screen.getByRole("button", { name: /again/i })).toBeEnabled();
});
```

Add API-client assertions for `scope`, `chapter_label`, and selection request bodies.

- [ ] **Step 2: Run focused tests and confirm failure**

```bash
rtk npm --prefix frontend test -- --run __tests__/review-grade-controls.test.tsx __tests__/api-client.test.ts
```

Expected: FAIL because the generated contract and shared grading modules do not exist.

- [ ] **Step 3: Regenerate types and implement the shared grading boundary**

```bash
rtk uv run python -m app.export_openapi ../openapi.json
rtk npm --prefix frontend run gen:api
```

Run the OpenAPI command with `backend` as the working directory and the npm command from the repository root. Update `getReviewQueue` to accept one options object instead of positional growth, then update its current callers in `review/page.tsx` and `FlashcardsClient.tsx` in the same task without changing their behavior yet. `gradeCardAndNotify` must await `gradeCard`, call `notifyReviewSettled()` only on success, and return the failure to the UI. `ReviewGradeControls` owns pending/error state, uses existing `previewIntervalDays()` and `formatIntervalPreview()`, disables all grades after a successful inline submission, and renders “Saved as {grade}.” A parent such as the review session may unmount it from `onGraded` to advance.

- [ ] **Step 4: Run type and component checks**

```bash
rtk npm --prefix frontend run typecheck
rtk npm --prefix frontend test -- --run __tests__/review-grade-controls.test.tsx __tests__/api-client.test.ts
```

Expected: PASS with no duplicate raw `gradeCard()` plus `notifyReviewSettled()` sequence in modified callers.

- [ ] **Step 5: Commit the shared contract**

```bash
rtk git add openapi.json frontend/lib/api/schema.d.ts frontend/lib/api/client.ts frontend/app/review/page.tsx frontend/components/flashcards/FlashcardsClient.tsx frontend/lib/review/gradeCardAndNotify.ts frontend/components/review/ReviewGradeControls.tsx frontend/__tests__/review-grade-controls.test.tsx frontend/__tests__/api-client.test.ts
rtk git commit -m "feat(review): centralize flashcard grading controls"
```

### Task 4: Add Inline Grading and Chapter Review to the Reader

**Files:**
- Modify: `frontend/components/reader/ReadingColumn.tsx`
- Modify: `frontend/components/reader/SectionCards.tsx`
- Modify: `frontend/__tests__/section-cards.test.tsx`
- Create: `frontend/__tests__/reading-column-cards.test.tsx`

**Interfaces:**
- Changes `SectionCards` props to include `courseId` and `chapterLabel` in addition to `sectionId`.
- Adds per-card grading after answer reveal through `ReviewGradeControls`.
- Adds “Review this chapter” linking to `/review?course={courseId}&scope=all&chapter={encodedChapterLabel}`.

- [ ] **Step 1: Write failing reader behavior tests**

```tsx
it("shows all four grade choices after an inline answer is revealed", async () => {
  render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
  await user.click(await screen.findByRole("button", { name: "Show answer" }));
  expect(screen.getByRole("button", { name: /again/i })).toBeVisible();
  expect(screen.getByRole("button", { name: /hard/i })).toBeVisible();
  expect(screen.getByRole("button", { name: /good/i })).toBeVisible();
  expect(screen.getByRole("button", { name: /easy/i })).toBeVisible();
});

it("links chapter review to every card in the current chapter", async () => {
  render(<SectionCards courseId="course-1" chapterLabel="Fractions & Ratios" sectionId="sec-1" />);
  expect(screen.getByRole("link", { name: "Review this chapter" })).toHaveAttribute(
    "href",
    "/review?course=course-1&scope=all&chapter=Fractions%20%26%20Ratios",
  );
});
```

Add a failed-grade test proving the card remains revealed and the student can retry. Preserve edit/delete behavior and its tests.

- [ ] **Step 2: Run reader tests and confirm failure**

```bash
rtk npm --prefix frontend test -- --run __tests__/section-cards.test.tsx __tests__/reading-column-cards.test.tsx
```

Expected: FAIL because `SectionCards` has no review context or grade controls.

- [ ] **Step 3: Add review behavior without coupling it to editing**

Pass `courseId` and the active section’s `chapter_label` from `ReadingColumn`. `SectionCards` loads editable card content from `listCards(sectionId)` and, in parallel, loads `getReviewQueue(courseId, { scope: "all", chapterLabel, limit: 200 })`; match scheduler metadata by card ID and render `ReviewGradeControls` only after answer reveal and outside edit/delete confirmation branches. After a successful grade, show “Saved as {grade}” while leaving the answer visible and keep that card’s grade controls locked to prevent accidental duplicate review events. Omit “Review this chapter” only for null front-matter labels.

- [ ] **Step 4: Run reader regressions**

```bash
rtk npm --prefix frontend test -- --run __tests__/section-cards.test.tsx __tests__/reading-column-cards.test.tsx __tests__/cards-cta.test.tsx
rtk npm --prefix frontend run typecheck
```

Expected: PASS, including edit, delete, generation-settled, and learner-grade behavior.

- [ ] **Step 5: Commit reader grading**

```bash
rtk git add frontend/components/reader/ReadingColumn.tsx frontend/components/reader/SectionCards.tsx frontend/__tests__/section-cards.test.tsx frontend/__tests__/reading-column-cards.test.tsx
rtk git commit -m "feat(reader): grade and review chapter flashcards"
```

### Task 5: Add Course, Chapter, and Needs-Attention Entry Points

**Files:**
- Modify: `frontend/components/flashcards/FlashcardsClient.tsx`
- Modify: `frontend/components/flashcards/ChapterDeckCard.tsx`
- Modify: `frontend/components/flashcards/CardsTable.tsx`
- Modify: `frontend/__tests__/flashcards-page.test.tsx`
- Modify: `frontend/__tests__/chapter-deck-card.test.tsx`
- Create: `frontend/__tests__/cards-table.test.tsx`

**Interfaces:**
- Adds course actions “Review due”, “Review all”, and “Needs attention”.
- Adds chapter action “Review chapter” using `scope=all` plus exact `chapter` query.
- Adds inline grade controls to browsed chapter cards after reveal.
- Displays total, due, new, and needs-attention counts from the all-card metadata and existing summary counts.

- [ ] **Step 1: Write failing library tests**

Assert the selected course renders:

```tsx
expect(screen.getByRole("link", { name: /review due/i })).toHaveAttribute(
  "href",
  "/review?course=course-1&scope=available&start=due",
);
expect(screen.getByRole("link", { name: /review all/i })).toHaveAttribute(
  "href",
  "/review?course=course-1&scope=all",
);
expect(screen.getByRole("link", { name: /needs attention/i })).toHaveAttribute(
  "href",
  "/review?course=course-1&scope=needs_attention",
);
```

Add assertions that each chapter review link carries the exact encoded chapter label and that browsed cards expose the same four grade controls as the review page.

- [ ] **Step 2: Run flashcard-page tests and confirm failure**

```bash
rtk npm --prefix frontend test -- --run __tests__/flashcards-page.test.tsx __tests__/chapter-deck-card.test.tsx __tests__/cards-table.test.tsx
```

Expected: FAIL because the library only links to due review and browsing has no grading.

- [ ] **Step 3: Implement explicit review entry points**

Use links rather than duplicating session state in `FlashcardsClient`. Load the course queue with `{ scope: "all", limit: 200 }` so every browsed card has scheduler metadata. Compute due cards from `is_due`, new cards from `is_new`, and needs-attention cards from `last_grade === 1`; do not infer due state merely from the presence of a review row. Keep chapter browsing, editing, and deletion where they already live.

Convert `CardsTable` from a static HTML table into an accessible stacked list while retaining its heading and compact metadata. Each row shows the front, status badges, and a “Show answer” button; expansion reveals the back plus `ReviewGradeControls`. This avoids interactive controls nested inside table-row navigation, works on narrow screens, and gives the approved chapter-card grading interaction an explicit reveal state. Update the component name only if every caller and test changes in the same commit.

- [ ] **Step 4: Run flashcard surface checks**

```bash
rtk npm --prefix frontend test -- --run __tests__/flashcards-page.test.tsx __tests__/chapter-deck-card.test.tsx __tests__/cards-table.test.tsx
rtk npm --prefix frontend run typecheck
```

Expected: PASS with links scoped to the currently selected course.

- [ ] **Step 5: Commit flashcard entry points**

```bash
rtk git add frontend/components/flashcards/FlashcardsClient.tsx frontend/components/flashcards/ChapterDeckCard.tsx frontend/components/flashcards/CardsTable.tsx frontend/__tests__/flashcards-page.test.tsx frontend/__tests__/chapter-deck-card.test.tsx frontend/__tests__/cards-table.test.tsx
rtk git commit -m "feat(flashcards): review by course or chapter"
```

### Task 6: Make Review Sessions URL-Driven and Replayable

**Files:**
- Create: `frontend/lib/review/sessionStorage.ts`
- Create: `frontend/__tests__/review-session-storage.test.ts`
- Modify: `frontend/app/review/page.tsx`
- Modify: `frontend/__tests__/review-page.test.tsx`

**Interfaces:**
- Produces `ReviewScope = "available" | "all" | "needs_attention"`.
- Produces versioned `ActiveReviewSession` and `CompletedReviewSession` storage contracts.
- Completed snapshot fields: `version`, `sessionId`, `courseId`, `scope`, `chapterLabel`, `endedAt`, `gradedTally`, `againCardIds`.
- Completed snapshots expire when `Date.now() - endedAt >= 86_400_000`.

- [ ] **Step 1: Write failing persistence and navigation tests**

```tsx
it("returns from completion to the course chooser without relying on remount", async () => {
  renderReviewAt("/review?course=course-1&scope=all");
  await completeCurrentSession(user);
  await user.click(screen.getByRole("button", { name: "Back to review" }));
  expect(screen.getByRole("heading", { name: "Ready to review" })).toBeVisible();
  expect(mockRouterReplace).toHaveBeenCalledWith("/review?course=course-1");
});

it("replays the exact Again cards from the completed session", async () => {
  seedCompletedSession({ againCardIds: ["card-3", "card-1"] });
  renderReviewAt("/review?course=course-1&completed=session-1");
  await user.click(screen.getByRole("button", { name: "Review missed (2)" }));
  expect(mockGetReviewSelection).toHaveBeenCalledWith("course-1", ["card-3", "card-1"]);
});
```

Add storage unit tests for malformed JSON, unknown versions, 24-hour expiry, no card content, and an empty `againCardIds` list. Add review-page tests for `scope=all`, `scope=needs_attention`, exact chapter labels, missing selected cards, failed grade submission, refresh on completed state, and browser back/forward query changes.

- [ ] **Step 2: Run review tests and confirm failure**

```bash
rtk npm --prefix frontend test -- --run __tests__/review-session-storage.test.ts __tests__/review-page.test.tsx
```

Expected: FAIL because completion is local component state and storage has no completed snapshot.

- [ ] **Step 3: Extract storage and make query state authoritative**

Move storage parsing/writing out of `page.tsx`. Include `scope` and `chapterLabel` in active sessions. On search-parameter changes, reconcile the current UI phase instead of relying on initial `useState`; explicit query intent supersedes stale active storage. Use `router.replace()` plus an immediate local phase transition for “Back to review,” making the action work even though the same route component stays mounted.

At completion, write the completed snapshot before clearing the active snapshot and route to `?course={id}&completed={sessionId}`. “Review missed” calls the exact-selection endpoint; missing/deleted IDs are reported once and the remaining cards continue. “Back to review” clears only the completed query, not the 24-hour snapshot. A new completed session replaces the prior completed snapshot.

- [ ] **Step 4: Reuse shared grade controls and await grade persistence**

Replace the review page’s duplicated grade-button markup with `ReviewGradeControls`. Advance only after a successful grade response so the completed tally and `againCardIds` cannot diverge from persisted server state. Keep keyboard handlers disabled while the request is pending and announce a failure without advancing.

This is an implementation-safety refinement of the approved optimistic interaction: the card remains visible during the typically local grade request rather than advancing and attempting a complex rollback. The visible pending state preserves responsiveness while guaranteeing the completed snapshot matches persisted scheduler state.

- [ ] **Step 5: Run review and integration tests**

```bash
rtk npm --prefix frontend test -- --run __tests__/review-session-storage.test.ts __tests__/review-grade-controls.test.tsx __tests__/review-page.test.tsx __tests__/flashcards-page.test.tsx __tests__/section-cards.test.tsx
rtk npm --prefix frontend run typecheck
rtk npm --prefix frontend run lint
```

Expected: PASS; same-route navigation, refresh, replay, and grade failures are deterministic.

- [ ] **Step 6: Commit session recovery**

```bash
rtk git add frontend/lib/review/sessionStorage.ts frontend/__tests__/review-session-storage.test.ts frontend/app/review/page.tsx frontend/__tests__/review-page.test.tsx
rtk git commit -m "fix(review): persist completion and replay missed cards"
```

### Task 7: Prove Unified Flashcard Review End to End

**Files:**
- Create: `frontend/e2e/flashcard-review-scopes.spec.ts`
- Modify: `ultraqa-comprehensive-feature-audit/report.md`

**Interfaces:**
- Consumes Tasks 1–6.
- Produces browser evidence for course-wide, chapter-wide, inline, completed-session, and missed-card review flows.

- [ ] **Step 1: Add deterministic browser scenarios**

Cover these user paths with seeded local fixtures or route interception:

```ts
test("student reviews every card in a course including not-due cards", runCourseAllReview);
test("student reviews only one chapter from the flashcards library", runChapterReview);
test("student grades a revealed card inside the chapter reader", runInlineReaderGrade);
test("completed review returns to chooser and replays exact missed cards", runCompletionReplay);
test("failed grade remains on the same card with retry guidance", runGradeFailureRecovery);
```

For each path, assert keyboard operation and run `@axe-core/playwright` after the interactive state is visible.

- [ ] **Step 2: Run backend review tests three times**

```bash
rtk uv run pytest -q backend/tests/test_review.py backend/tests/test_learner_scoping.py backend/tests/test_review_availability_service.py
rtk uv run pytest -q backend/tests/test_review.py backend/tests/test_learner_scoping.py backend/tests/test_review_availability_service.py
rtk uv run pytest -q backend/tests/test_review.py backend/tests/test_learner_scoping.py backend/tests/test_review_availability_service.py
```

Expected: all three runs pass with stable order.

- [ ] **Step 3: Run frontend and browser verification**

```bash
rtk npm --prefix frontend run typecheck
rtk npm --prefix frontend run lint
rtk npm --prefix frontend test -- --run
rtk npm --prefix frontend run test:e2e -- flashcard-review-scopes.spec.ts
```

Expected: PASS with no critical accessibility violations.

- [ ] **Step 4: Run the repository release gate**

```bash
rtk ./build.sh
```

Expected: `BUILD OK`.

- [ ] **Step 5: Record evidence and commit the completed slice**

Update the QA report with exact test counts, scope semantics, replay behavior, keyboard coverage, and any explicitly deferred risk.

```bash
rtk git add frontend/e2e/flashcard-review-scopes.spec.ts ultraqa-comprehensive-feature-audit/report.md
rtk git commit -m "test(e2e): verify unified flashcard review"
```
