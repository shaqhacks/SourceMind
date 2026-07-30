# Reader Popover Lifecycle and Lint Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make reader popover state section-scoped, eliminate all current frontend lint errors, and make lint part of the canonical build gate.

**Architecture:** `CourseReader` owns the section boundary and remounts `ReadingColumn` when `activeSection.id` changes. `ReadingColumn` keeps only section-local transient popover state and no longer clears that state through an effect. The canonical root build script explicitly invokes frontend ESLint because Next.js 16 does not lint during `next build`.

**Tech Stack:** Next.js 16.2.10, React 19.2.4, TypeScript 5, Vitest 4.1.9, Testing Library, ESLint 9, Bash, FastAPI/Pytest verification.

## Global Constraints

- Do not weaken, disable, or locally suppress React hook or ESLint rules.
- Do not modify fonts, package versions, dependency ranges, or lockfiles.
- Preserve typography, view mode, chat, progress, sidebar, and course-level state across section navigation.
- Discard highlight-selection, highlight-edit, note-composer, and note-edit popovers on every section change.
- Use the existing `build.sh` as the single local and CI gate.
- Follow strict test-first sequencing: establish behavior coverage and capture the failing lint signal before modifying production files.
- Per the owner’s principal-engineer directive, this plan specifies behavior, interfaces, and verification without supplying implementation code bodies.

---

## File map

- Create `frontend/__tests__/reader/reading-column-popover-lifecycle.test.tsx`: integration coverage for highlight and note popover disposal through real `CourseReader` navigation.
- Modify `frontend/components/reader/CourseReader.tsx`: establish the `activeSection.id` lifecycle boundary at the `ReadingColumn` instance.
- Modify `frontend/components/reader/ReadingColumn.tsx`: order note state before all callback references and remove effect-driven reset logic.
- Modify `build.sh`: invoke the existing frontend lint script inside the canonical gate.

### Task 1: Lock the navigation behavior and capture the failing lint baseline

**Files:**
- Create: `frontend/__tests__/reader/reading-column-popover-lifecycle.test.tsx`
- Reference: `frontend/__tests__/annotations/selection-popover.test.tsx`
- Reference: `frontend/__tests__/reader/pdf-note.test.tsx`
- Reference: `frontend/__tests__/course-reader.test.tsx`

**Interfaces:**
- Consumes: `CourseReader`, the existing `SelectionPopover` accessible name `Selection actions`, the existing `NotePopover` accessible name `Add note`, and the existing next-chapter navigation button.
- Produces: two behavior-lock tests that remain valid regardless of whether disposal is implemented by an effect or a remount.

- [ ] **Step 1: Create a focused two-section reader fixture**

  Use two sections with distinct identifiers, titles, bodies, and non-null asset identifiers. Mock the same API boundaries already mocked by the three reference suites. Mock `PagesView` only at the renderer boundary so it exposes a deterministic note-gutter control that calls the real `onNoteGutterClick` callback; keep `ReadingColumn`, `CourseReader`, and their state ownership real.

- [ ] **Step 2: Add the highlight-popover lifecycle characterization**

  Render in source mode, create a real text selection using the existing TreeWalker/Range convention, open `Selection actions`, navigate with the visible next-chapter button, and assert the second chapter is active and `Selection actions` is absent.

- [ ] **Step 3: Add the note-popover lifecycle characterization**

  Persist Pages view through the established `smv2.readerView.<courseId>` key before rendering. Trigger the mocked page gutter so the real `ReadingColumn` opens `Add note`, navigate with the visible next-chapter button, and assert the second chapter is active and `Add note` is absent.

- [ ] **Step 4: Run the focused tests before production changes**

  Run: `npm test -- --run __tests__/reader/reading-column-popover-lifecycle.test.tsx`

  Expected: both characterization tests PASS because the current reset effect already preserves the required user-visible behavior. Treat an immediate pass as intentional behavior locking, not as proof that the lint defect is fixed.

- [ ] **Step 5: Capture the actual RED signal**

  Run: `./node_modules/.bin/eslint components/reader/ReadingColumn.tsx`

  Expected: FAIL with 12 errors, including access-before-declaration at the current note-setter call sites and synchronous set-state-in-effect at the section reset effect.

- [ ] **Step 6: Commit the behavior lock**

  Stage only the new test file and commit with: `test: lock reader popover lifecycle`

### Task 2: Replace effect-driven cleanup with section-scoped ownership

**Files:**
- Modify: `frontend/components/reader/CourseReader.tsx` at the `ReadingColumn` render
- Modify: `frontend/components/reader/ReadingColumn.tsx` around the note state, pages callbacks, and section-reset effect
- Test: `frontend/__tests__/reader/reading-column-popover-lifecycle.test.tsx`

**Interfaces:**
- Consumes: `activeSection.id` from `CourseReader`; existing local popover state and callbacks in `ReadingColumn`.
- Produces: a keyed `ReadingColumn` lifecycle boundary; the same public props and user-visible behavior; zero effect-driven popover resets.

- [ ] **Step 1: Establish the narrow lifecycle boundary**

  Key the `ReadingColumn` instance by `activeSection.id`. Do not key the surrounding reader shell, sidebar, top bar, chat drawer, notes panel, or `CourseReader` itself.

- [ ] **Step 2: Make note state declaration order explicit**

  Move the note composer and note edit state declarations before the first pages callback that references their setters. Keep state shapes, initial values, callback semantics, and API mutations unchanged.

- [ ] **Step 3: Remove the obsolete reset mechanism**

  Delete the section-change effect that clears six popover states. Remove `useEffect` from the `ReadingColumn` React import if no other effect remains in that file. Do not replace the effect with event-handler resets or lint suppressions.

- [ ] **Step 4: Verify GREEN at the original failure boundary**

  Run: `./node_modules/.bin/eslint components/reader/ReadingColumn.tsx`

  Expected: PASS with zero errors and zero warnings.

- [ ] **Step 5: Verify behavior remained locked**

  Run: `npm test -- --run __tests__/reader/reading-column-popover-lifecycle.test.tsx`

  Expected: both lifecycle tests PASS. Confirm the tests navigate through `CourseReader`; a prop-only rerender of `ReadingColumn` would not validate the selected ownership boundary.

- [ ] **Step 6: Run adjacent reader regression suites**

  Run: `npm test -- --run __tests__/annotations/selection-popover.test.tsx __tests__/reader/pdf-highlight-edit.test.tsx __tests__/reader/note-popover.test.tsx __tests__/reader/pdf-note.test.tsx __tests__/course-reader.test.tsx`

  Expected: all selected suites PASS with no unhandled promise or React lifecycle warnings.

- [ ] **Step 7: Commit the lifecycle repair**

  Stage the two production files and commit with: `fix: scope reader popovers to active section`

### Task 3: Put frontend lint into the canonical build gate

**Files:**
- Modify: `build.sh` after frontend typecheck and before frontend tests/build
- Reference: `frontend/package.json` script `lint`

**Interfaces:**
- Consumes: existing `npm run lint` script.
- Produces: a non-zero canonical build result whenever frontend lint fails.

- [ ] **Step 1: Confirm the gate omission before editing**

  Run: `rg -n "npm run lint" build.sh`

  Expected: no match.

- [ ] **Step 2: Add the explicit frontend lint stage**

  Add a labeled frontend lint phase after typecheck and before tests. Invoke only the existing package script; do not introduce a second ESLint configuration or CI-only command.

- [ ] **Step 3: Validate shell syntax and lint execution**

  Run: `bash -n build.sh`

  Expected: PASS with no output.

  Run: `npm run lint`

  Expected: PASS with zero errors and zero warnings.

- [ ] **Step 4: Confirm the gate contains exactly one lint invocation**

  Run: `rg -n "npm run lint" build.sh`

  Expected: exactly one match in the frontend validation sequence.

- [ ] **Step 5: Commit the gate repair**

  Stage only `build.sh` and commit with: `build: enforce frontend lint`

### Task 4: Full verification and review handoff

**Files:**
- Verify only; no planned file modifications.

**Interfaces:**
- Consumes: the completed lifecycle and gate changes.
- Produces: fresh evidence for every completion claim and an explicit build limitation if external font access remains unavailable.

- [ ] **Step 1: Run the complete frontend static and behavioral checks**

  Run from `frontend/`:

  - `npm run lint`
  - `npm run typecheck`
  - `npm test -- --run`

  Expected: lint and typecheck exit zero; all frontend tests pass.

- [ ] **Step 2: Run the backend regression suite**

  Run from `backend/`: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider`

  Expected: all backend tests pass. Existing third-party deprecation warnings may remain because dependency changes are explicitly out of scope.

- [ ] **Step 3: Attempt the canonical build**

  Run from the repository root: `./build.sh`

  Expected when network access is available: `BUILD OK`, including the newly added lint phase. If Google Fonts cannot be fetched because network egress is blocked, record the production build as unverified and include the exact font-fetch failure; do not alter fonts or dependencies in this task.

- [ ] **Step 4: Inspect scope and repository state**

  Run:

  - `git diff --check`
  - `git status --short`
  - `git log -4 --oneline`

  Expected: no whitespace errors; only intentional files are changed or committed; commits separate behavior lock, lifecycle repair, and gate repair.

- [ ] **Step 5: Principal-engineer review checklist**

  Verify that the diff contains no lint suppressions, no setter dependency padding, no font/dependency changes, no broader keyed subtree, and no unrelated refactor. Confirm both popover families have explicit navigation coverage and persistent course-level state remains outside the keyed boundary.
