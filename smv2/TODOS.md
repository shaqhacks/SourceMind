# TODOS

## Skills / Competency Backend

### Graph re-import prune semantics
**Priority:** P2
`import_graph` upserts concepts but never deletes omitted ones → unbounded growth across re-imports. Deleting could orphan historical curriculum revisions and evidence mappings for renamed slugs. Decide: tombstone, merge, or document keep-forever.

### get_skill_detail recomputes the whole course map per concept click
**Priority:** P3
Scope queries to the requested concept's neighborhood or cache per (course_id, data-version) if skill pages ever measure slow. Bounded today by the 500-concept/2000-edge import caps.

## Annotations (Highlights / Notes)

### Ownership scoping on annotation mutations
**Priority:** P2
`PATCH/DELETE /api/highlights/{id}` and `/api/notes/{id}` authorize by bare UUID (BOLA pattern; theoretical while single-user/localhost). Fix: nest under course or verify course membership. Do before any multi-user/remote exposure.

### Annotation cache ordering
**Priority:** P1
`useHighlights`/`useNotes`: a stale list GET can overwrite a fresh create; an older failed PATCH can roll back a newer success. Fix: request generations + per-record mutation sequencing.

### Chat-selection grounding rarely engages
**Priority:** P2
`_build_selection_block` searches raw `body_md` with rendered-space selection text, so formatted/pages selections silently degrade to quote-only (red team). Fix: match against a whitespace-normalized `body_md` copy and map indices back. Docstring corrected 2026-07-26; behavior unchanged.

### >2000-char source selections
**Priority:** P2
Pages-mode popover offers highlight/add-to-chat but both schemas cap `exact` at 2000 → 422. UX call: truncate (PDF path precedent), gate with hint, or raise caps.

## Flashcards / Tests UI

### Chapter due-counts wrong past 200 queued cards
**Priority:** P2
`FlashcardsClient` infers per-chapter counts from the first `MAX_QUEUE_FETCH=200` queue entries; headline is right, chapter cards undercount. Fix: server-side per-chapter aggregates.

## Learning Model Validation

### Prospective challenger promotion
**Priority:** P1
BKT, PFA, and DAS3H-style estimates run in shadow mode. Do not promote one to learner-facing or scheduling authority until the prospective evaluation meets the documented calibration, delayed-prediction, stability, subgroup, and interpretability gates.

### Instructor agreement sample
**Priority:** P1
Collect blinded instructor judgments across enough learners, concepts, and evidence patterns to report agreement beyond the insufficient-sample state. Resolve every post-reveal disagreement reason before including it in aggregate agreement.

### Delayed-retention pilot
**Priority:** P1
Run the documented randomized pilot with unseen delayed probes. Report assignment balance, attrition, workload, and confidence intervals; do not claim a causal benefit below the configured sample floor.

## Frontend Structure

### Course-level tab navigation (Reader · Cards · Quizzes · Map)
**Priority:** P3
Shared course header nav making the surfaces one click apart. Cards/quizzes are currently reached via inline CTAs and separate routes; start by extracting the map route's header upward. Wireframe reference: `~/.gstack/projects/smv2/designs/mockup-20260726/mastery-map-wireframe-v4.png`. Depends on: skills routes (shipped).

### Structural refactors (from maintainability sweep — own pass, not landing scope)
**Priority:** P3
Generic `useSectionScopedCrud<T>` hook (useHighlights/useNotes share ~70 lines of plumbing); shared `CourseSwitcher` (tests page `<select>` vs flashcards tablist); shared `Breadcrumb`; HintRow reuse in review page; `useSkillDetail` hook mirroring `useSkillMap`; move `useCourseTitle` to lib/hooks/; `findActiveChapterTestJob` into client.ts.

### UX polish (from design review — informational)
**Priority:** P3
Note-gutter affordance nearly invisible at rest (5% tint, no glyph) — add a persistent low-key cue. Enhanced-HTML view silently hides existing highlights/notes (no painter there yet) — show a non-blocking notice like the `converting` state. 24px swatch/pin touch targets — add hit-slop if tablet use matters; popovers lack a horizontal viewport clamp near screen edges.

## Completed

### Home page eagerly loads YouTube embed (ISSUE-002)
Resolved by removing the learning-science video section entirely (owner decision — went further than the planned lazy-load facade). **Completed:** 2026-07-28.
