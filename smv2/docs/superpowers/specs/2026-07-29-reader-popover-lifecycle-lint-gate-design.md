# Reader Popover Lifecycle and Lint Gate — Design

- Date: 2026-07-29
- Status: owner-approved design; no implementation yet
- Scope: confirmed frontend lint failures and the CI lint-gate omission

## Goal

Restore a clean frontend lint result and prevent the same class of regression
from passing the repository's canonical build gate. Preserve existing reader
behavior except that all open highlight and note popovers are discarded when
the active section changes.

## Decisions

1. `ReadingColumn` is section-scoped. The active section identifier defines a
   lifecycle boundary for its transient UI state.
2. Highlight-selection, highlight-edit, note-composer, and note-edit popovers
   do not survive section navigation because their anchors refer to DOM nodes,
   ranges, notes, or geometry owned by the previous section.
3. Persistent reader state remains outside the section-scoped subtree. This
   includes typography, view mode, chat state, navigation/progress state, and
   other course-level preferences.
4. The fix covers confirmed bugs only. Google Fonts build access and backend
   dependency deprecation warnings remain unchanged because neither was
   established as an application defect during the review.

## Design

### State ownership

`CourseReader` will key `ReadingColumn` by the active section identifier. A
section change therefore remounts `ReadingColumn`, naturally discarding all
component-local transient state. This replaces the current effect that reacts
to `section.id` by synchronously clearing six state values after render.

The key belongs on `ReadingColumn`, not on `CourseReader` or the surrounding
reader shell. Keying a broader subtree would incorrectly reset persistent
course-level state. Keying only the inner source/pages DOM wrappers is
insufficient because the popover state is owned by `ReadingColumn` itself.

### Hook and callback ordering

The note composer and note edit state declarations will precede every callback
that references their setters. This makes the lexical and compiler-visible
dependency order explicit and removes the current access-before-declaration
diagnostics. Existing callback behavior and mutation semantics remain
unchanged.

### Canonical validation gate

The existing frontend `lint` script will be invoked explicitly by `build.sh`.
Next.js 16 no longer runs ESLint as part of `next build`, so the repository
gate must own this check directly. Lint will run before the production build,
ensuring React compiler and ESLint violations fail locally and in CI.

## Testing

1. Add a reader regression test that opens a transient popover, navigates to a
   different section, and verifies that the old popover is no longer present.
2. Cover both interaction families: one highlight popover and one note
   popover must each be opened before navigation and absent afterward. Tests
   may share setup helpers, but both behaviors require explicit assertions.
3. Run the focused reader test, the full frontend test suite, frontend
   typecheck, and frontend lint.
4. Run backend tests to confirm the build-gate edit does not alter backend
   behavior.
5. Attempt the production build. If the environment cannot fetch configured
   Google Fonts, report that limitation separately rather than classifying it
   as a regression from this change.

## Risks and footguns

- **Over-broad remounting:** placing the key above `ReadingColumn` could reset
  chat, typography, or navigation state. The lifecycle boundary must remain on
  `ReadingColumn` itself.
- **Scroll and focus behavior:** remounting must preserve the existing
  navigation contract for scroll position and heading focus. The regression
  test should include the established section-navigation path rather than a
  synthetic prop-only rerender when practical.
- **Duplicate data loading:** remounting restarts `ReadingColumn` hooks. This is
  appropriate because highlights and notes are section-scoped, but tests must
  not assume their prior hook instances survive navigation.
- **Partial lint repair:** suppressing React hook rules or adding setters to
  dependency arrays would mask the ownership problem. The design fixes state
  lifetime and declaration order instead of weakening validation.
- **Gate drift:** adding a separate CI-only lint command would leave local and
  CI behavior inconsistent. `build.sh` remains the single canonical gate.

## Acceptance criteria

- `npm run lint` reports zero errors.
- The section-navigation popover regression test passes.
- All existing frontend tests and TypeScript checks pass.
- Backend tests remain green.
- `build.sh` explicitly runs frontend lint.
- No lint rules are disabled to obtain a passing result.
- No font or dependency changes are included in the implementation diff.
