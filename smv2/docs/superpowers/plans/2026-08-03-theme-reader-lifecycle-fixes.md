# Theme Bootstrap and Reader Lifecycle Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the production theme bootstrap and remove the 12 `ReadingColumn` React lint errors while preserving the current reader behavior.

**Architecture:** Move the theme contract and pre-paint script into a server-safe module shared by the root layout and client hook. Give `ReadingColumn` section-based React identity so section-local transient state resets by remount instead of synchronous effect updates, then restore declaration order so callbacks only reference initialized state bindings.

**Tech Stack:** Next.js 16, React 19, TypeScript 5, Vitest 4, Testing Library, ESLint with React Compiler rules.

## Global Constraints

- Preserve the storage key `smv2.theme` and the preference values `system`, `light`, and `dark` exactly.
- Keep the pre-paint script synchronous in `<head>` and wrapped in `try/catch`.
- Preserve the server-rendered `data-theme="light"` fallback.
- A section change resets only `ReadingColumn`-local transient UI; persisted annotations and course-level state remain unchanged.
- Add no lint suppression, duplicate theme key, dependency, popover reducer, or unrelated refactor.
- Preserve all unrelated working-tree changes and do not commit unless the user explicitly requests it.
- This plan intentionally specifies interfaces, behaviors, and review gates without implementation bodies, following the repository's Principal-Engineer Review Mode.

---

## File Structure

- Create `frontend/lib/theme/bootstrap.ts`: server-safe theme types, canonical storage key, preference validation, and the generated pre-paint script.
- Create `frontend/__tests__/theme-bootstrap.test.ts`: direct regression coverage for the pre-paint script and exact storage key.
- Modify `frontend/lib/hooks/useTheme.ts`: consume the shared server-safe contract instead of defining its own key and types.
- Modify `frontend/app/layout.tsx`: consume the server-safe script without importing a client module.
- Modify `frontend/__tests__/course-reader.test.tsx`: characterize section-navigation disposal of transient reader UI.
- Modify `frontend/components/reader/CourseReader.tsx`: key the `ReadingColumn` subtree by active section.
- Modify `frontend/components/reader/ReadingColumn.tsx`: remove effect-based resets and restore state declaration order.

### Task 1: Establish the server-safe theme boundary

**Files:**

- Create: `frontend/lib/theme/bootstrap.ts`
- Create: `frontend/__tests__/theme-bootstrap.test.ts`
- Modify: `frontend/lib/hooks/useTheme.ts:1-25`
- Modify: `frontend/app/layout.tsx:1-65`

**Interfaces:**

- Produces: `THEME_STORAGE_KEY` with literal value `smv2.theme`.
- Produces: exported `ThemePreference` union `system | light | dark`.
- Produces: exported `EffectiveTheme` union `light | dark`.
- Produces: exported `THEME_BOOTSTRAP_SCRIPT: string` generated entirely in the server-safe module.
- Consumes: `window.localStorage`, `window.matchMedia("(prefers-color-scheme: dark)")`, and `document.documentElement.dataset.theme` only when the generated script executes in the browser.

- [x] **Step 1: Add the failing theme-bootstrap test**

Create a table-driven test with literal expected themes for these cases:

| Stored value | System is dark | Expected `data-theme` |
| --- | --- | --- |
| `dark` | false | `dark` |
| `light` | true | `light` |
| `system` | true | `dark` |
| `system` | false | `light` |
| missing | true | `dark` |
| invalid value | false | `light` |

For each case, control `localStorage` and `matchMedia`, execute `THEME_BOOTSTRAP_SCRIPT` in the test DOM, and assert the literal result. Add separate assertions that the script contains `localStorage.getItem("smv2.theme")` and does not contain `getItem(undefined)`.

- [x] **Step 2: Run the focused test and confirm RED**

Run: `cd frontend && npm test -- --run __tests__/theme-bootstrap.test.ts`

Expected: FAIL because `frontend/lib/theme/bootstrap.ts` and `THEME_BOOTSTRAP_SCRIPT` do not exist.

- [x] **Step 3: Implement the server-safe module**

Create the four exported interfaces listed above. Keep preference validation private. Construct the script from the canonical key so the storage key cannot drift between the script and hydrated hook. Preserve the existing resolution semantics and exception boundary from `layout.tsx`.

Principal-engineer review gate: reject an implementation that contains `"use client"`, imports React, duplicates `smv2.theme`, accepts arbitrary theme strings, or exposes browser globals at module evaluation time.

- [x] **Step 4: Rewire the client hook and root layout**

Make `useTheme.ts` import the shared key and types while retaining its existing subscription and DOM-application behavior. Make `layout.tsx` import only `THEME_BOOTSTRAP_SCRIPT` from the server-safe module, delete its local script construction, and pass that exported string to the existing `<script>` element.

Principal-engineer review gate: `layout.tsx` must have no import path under `lib/hooks`, and `useTheme.ts` must no longer declare its own storage key or theme unions.

- [x] **Step 5: Verify GREEN at the theme boundary**

Run:

- `cd frontend && npm test -- --run __tests__/theme-bootstrap.test.ts __tests__/theme-toggle.test.tsx`
- `cd frontend && npx eslint app/layout.tsx lib/theme/bootstrap.ts lib/hooks/useTheme.ts __tests__/theme-bootstrap.test.ts __tests__/theme-toggle.test.tsx`
- `cd frontend && npm run typecheck`

Expected: both test files pass, targeted ESLint exits 0, and TypeScript exits 0.

- [x] **Step 6: Verify the compiled production artifact**

Run `cd frontend && npm run build`, then inspect `frontend/.next/server`.

Required artifact assertions:

- At least one generated HTML/server artifact contains `localStorage.getItem("smv2.theme")`.
- No generated HTML/server artifact contains `localStorage.getItem(undefined)`.
- The build exits 0 without Google Fonts network requests.

### Task 2: Make transient reader state section-owned

**Files:**

- Modify: `frontend/__tests__/course-reader.test.tsx`
- Modify: `frontend/components/reader/CourseReader.tsx:455-481`
- Modify: `frontend/components/reader/ReadingColumn.tsx:336-600`

**Interfaces:**

- Consumes: `activeSection.id` as the React identity of the `ReadingColumn` subtree.
- Preserves: `useHighlights(courseId, section.id)` and `useNotes(courseId, section.id)` as the persisted annotation boundaries.
- Preserves: all existing `ReadingColumnProps` without adding a reset callback or lifecycle prop.
- Produces: a fresh set of six transient popover states whenever the active section identity changes.

- [x] **Step 1: Add a passing characterization test for existing section-change behavior**

Extend the existing `CourseReader` integration suite. Render section one, open a real transient reader dialog using the existing selection-popover integration setup, navigate to section two through the chapter-outline control, and assert that:

- Section two's body is visible.
- The section-one dialog is absent.
- No annotation deletion or update API was called.

Run: `cd frontend && npm test -- --run __tests__/course-reader.test.tsx`

Expected before refactoring: PASS. This locks the user-visible behavior currently provided by the problematic effect.

- [x] **Step 2: Confirm the static-analysis RED state**

Run: `cd frontend && npx eslint components/reader/ReadingColumn.tsx components/reader/CourseReader.tsx __tests__/course-reader.test.tsx`

Expected: FAIL with the current forward-reference, manual-memoization, and synchronous-state-in-effect diagnostics. Record the exact count before editing; the observed baseline is 12 errors in `ReadingColumn.tsx`.

- [x] **Step 3: Move lifecycle ownership to the parent identity boundary**

Key the `ReadingColumn` element by `activeSection.id` in `CourseReader`. Do not key `CourseReader`, the surrounding reader shell, chat drawer, notes panel, usage footer, or typography store.

Principal-engineer review gate: only the section-scoped reading subtree may remount. Sidebar collapse, view preference, typography preference, chat state, outline state, and course progress must retain their existing ownership.

- [x] **Step 4: Remove the effect reset and repair declaration order**

Delete the section-change reset effect and remove `useEffect` from the React import if it has no remaining consumer. Move the note-composer and note-edit state declarations above the first page-selection callback that closes them. Keep all six popover states local to `ReadingColumn`.

Retain the existing callback dependency arrays on the first pass. If React Compiler still reports a dependency mismatch after declaration order is corrected, add only the stable state setter named by that diagnostic; do not add an ESLint disable and do not rewrite unrelated callbacks.

- [x] **Step 5: Verify reader behavior and lint GREEN**

Run:

- `cd frontend && npm test -- --run __tests__/course-reader.test.tsx __tests__/annotations/selection-popover.test.tsx __tests__/annotations/highlight-edit-popover.test.tsx __tests__/reader/pdf-note.test.tsx`
- `cd frontend && npx eslint components/reader/ReadingColumn.tsx components/reader/CourseReader.tsx __tests__/course-reader.test.tsx`
- `cd frontend && npm run typecheck`

Expected: all focused reader tests pass, the targeted lint command reports zero errors, and TypeScript exits 0.

### Task 3: Run the complete regression gate

**Files:**

- Verify only; no additional source files are authorized by this task.

**Interfaces:**

- Consumes: the completed theme and reader tasks.
- Produces: evidence that the current working tree meets the approved success criteria.

- [x] **Step 1: Run the full frontend quality gate**

Run sequentially:

- `cd frontend && npm run lint`
- `cd frontend && npm run typecheck`
- `cd frontend && npm test -- --run`
- `cd frontend && npm run build`

Expected: all four commands exit 0. The frontend suite baseline before these changes is 84 files and 633 tests; the final count must be at least that baseline plus the newly added theme and reader coverage.

- [x] **Step 2: Verify compiled theme behavior and source boundaries**

Inspect the production artifacts and source tree for all four invariants:

- Compiled script reads `smv2.theme`.
- Compiled script never reads `undefined`.
- `layout.tsx` does not import from `lib/hooks/useTheme`.
- Exactly one source declaration of the literal `smv2.theme` remains.

- [x] **Step 3: Verify repository hygiene**

Run:

- `git diff --check`
- `git status --short frontend/app/layout.tsx frontend/lib/theme frontend/lib/hooks/useTheme.ts frontend/components/reader/ReadingColumn.tsx frontend/components/reader/CourseReader.tsx frontend/__tests__/theme-bootstrap.test.ts frontend/__tests__/course-reader.test.tsx`

Expected: no whitespace errors and no files outside the approved scope introduced by this implementation.
