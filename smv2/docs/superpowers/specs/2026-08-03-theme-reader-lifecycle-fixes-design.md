# Theme Bootstrap and Reader Lifecycle Fixes Design

Date: 2026-08-03

## Goal

Repair two confirmed frontend defects without changing the intended user experience:

1. The production pre-paint theme script must read the persisted `smv2.theme` preference instead of calling `localStorage.getItem(undefined)`.
2. Section navigation must clear transient reader selections and highlight/note popovers without synchronous state resets in an effect or React Compiler lint failures.

## Root causes

### Theme bootstrap

`frontend/app/layout.tsx` is a server component but imports `THEME_STORAGE_KEY` from `frontend/lib/hooks/useTheme.ts`, which is a `"use client"` module. Next.js represents that export as a client reference when compiling the server layout. Serializing the reference with `JSON.stringify` produces `undefined`, so the generated production HTML reads the wrong local-storage key.

### Reader lifecycle

`ReadingColumn` owns transient UI state whose identity is the current section: source-selection popovers, existing-highlight popovers, page-selection popovers, page-highlight popovers, note creation, and note editing. Commit `00d9d66` added an effect that synchronously clears all six states after `section.id` changes. This creates an avoidable second render and violates the React `set-state-in-effect` rule. The same change references note state setters from callbacks declared before those setters, preventing React Compiler from preserving the manual memoization.

## Architecture

### Server-safe theme boundary

Create a server-safe theme module under `frontend/lib/theme/`. It will own:

- The canonical storage key `smv2.theme`.
- The supported preference values: `system`, `light`, and `dark`.
- A pure function that produces the pre-paint bootstrap script.

`frontend/app/layout.tsx` will import the ready-to-render bootstrap script from this server-safe module. `frontend/lib/hooks/useTheme.ts` will import the same storage key and preference contract. The server layout will not import anything from a `"use client"` module.

The bootstrap script will continue to run synchronously in `<head>` before first paint. It will read the stored preference, fall back to `system` for invalid or missing values, resolve the operating-system color scheme through `matchMedia`, and set `document.documentElement.dataset.theme` to `light` or `dark`.

### Section-owned reader state

`CourseReader` will render `ReadingColumn` with `key={activeSection.id}`. A section change therefore gives the reader subtree a new React identity, discarding every section-local transient state value before the new section is rendered. This replaces the synchronous reset effect and follows React's documented keyed-state reset mechanism.

Persisted highlights and notes remain owned by the backend. `useHighlights(courseId, section.id)` and `useNotes(courseId, section.id)` will mount for the new section and load that section's persisted records normally. Typography preferences, sidebar state, chat state, course navigation, and lesson progress remain owned above `ReadingColumn` and therefore survive section changes.

Within `ReadingColumn`, note state declarations will move before the page-selection callbacks that consume their setters. Manual memoization will be retained only where it has a real consumer requirement; all retained callback dependency arrays must match React Compiler's inferred dependencies. No lint suppression will be added.

## Behavior

### Theme

- A stored `dark` preference applies `data-theme="dark"` before first paint.
- A stored `light` preference applies `data-theme="light"` before first paint.
- A stored `system`, absent, or invalid preference follows `prefers-color-scheme`.
- Hydrated theme controls continue using the same storage key and remain synchronized.

### Reader

Changing sections closes every open reader-local selection, highlight, and note popover.
- Navigating between source, pages, and lesson views within the same section retains the existing intended behavior.
- Persisted highlights and notes are not deleted or rewritten by a section change.
- Course-level state outside `ReadingColumn` is preserved.

## Error handling

The theme bootstrap remains wrapped in `try/catch` because local storage or `matchMedia` may be unavailable. Failure leaves the server-rendered `data-theme="light"` fallback in place and does not block rendering.

Reader remounting requires no recovery branch: transient UI state is disposable by definition, while persisted annotations retain their existing API error handling.

## Testing

### Theme regression

Add focused tests for the server-safe bootstrap generator that execute the produced script in the test DOM and verify:

- `dark`, `light`, and `system` resolve correctly.
- Invalid and missing stored values use the system preference.
- The script reads the exact `smv2.theme` key.

Run a production build and inspect the generated HTML to confirm it contains `localStorage.getItem("smv2.theme")` and does not contain `localStorage.getItem(undefined)`.

### Reader regression

Add or extend a `CourseReader` integration test that opens representative transient reader UI, changes the active section, and verifies the old popover is absent. Existing annotation tests continue to prove persisted highlights and notes load for their section.

Run full ESLint to prove all 12 current `ReadingColumn` errors are removed without suppressions. Run frontend tests, TypeScript, both supported production builders when necessary to isolate environment behavior, and `git diff --check`.

## Non-goals

- Redesigning theme controls or adding theme choices.
- Refactoring all reader popovers into a reducer or state machine.
- Changing annotation persistence, API contracts, keyboard navigation, typography preferences, chat behavior, or lesson progress.
- Fixing unrelated backend deprecation warnings or adding Ruff to the dependency set.

## Success criteria

- Production HTML reads `smv2.theme`, never `undefined`.
- Persisted theme preference is applied before first paint.
- Section navigation resets only `ReadingColumn`-local transient state.
- Full frontend ESLint, TypeScript, tests, and production build pass.
- No lint suppression, duplicated theme key, new dependency, or unrelated refactor is introduced.
