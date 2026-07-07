# SMV2 UI Overhaul + Rich Landing Page — Design Spec

Date: 2026-07-07
Status: Approved (pending user spec review)
Scope: `smv2/frontend` only. Zero backend changes. Zero new dependencies.

## Context

User request: full UI analysis, make the frontend much more appealing, add a landing
page showing flashcards due, quizzes due, and embedded YouTube videos about learning
science (spaced repetition, learning styles).

Analysis findings (2026-07-07):

- Stack: Tailwind v4 CSS-first, design tokens as CSS variables in `app/globals.css`,
  3-state theme (system/light/dark) via `data-theme` attribute, WCAG-engineered
  contrast, SSE + `reviewBus` event model (no polling). Accessibility is a genuine
  strength (`:focus-visible` ring, aria throughout, reduced-motion reset).
- The dashboard (`app/page.tsx`) already has ContinueCard, ReviewCard, StudyNextList,
  and a course grid — the landing page is an expansion + restyle, not greenfield.
- Ranked weaknesses: (1) no shared UI primitives — button/badge/card styles are
  copy-pasted across ~10 files; (2) body font is Arial (`globals.css:91`) despite
  Geist being loaded; (3) status conveyed by colored text only, no filled pills;
  (4) review grade buttons (Again/Hard/Good/Easy) are visually identical;
  (5) loading states are bare text, no skeletons; (6) inconsistent empty states;
  (7) reader TopBar has 8+ controls in one non-wrapping row; (8) ThemeToggle only
  reachable inside the reader; (9) flat type scale and inconsistent page paddings.
- Backend data reality: cards have real SM-2 scheduling (`GET /api/review/summary`
  returns `due_total`, `backlog_warning`, and per-course `due_count`/`new_count`).
  Tests/quizzes have NO "due" concept — only attempt history via
  `ChapterOut.test_stats` (`attempts`, `best_score`, `latest_score`).

## Decisions (user-confirmed)

1. **"Quizzes due" = derived frontend-only.** Chapters with `attempts === 0`
   ("not attempted") or `best_score < 70` ("retake suggested"). No backend scheduler.
2. **Videos = direct iframes**, using `youtube-nocookie.com` and `loading="lazy"`
   (same UX as plain embeds, less tracking, no cost).
3. **Visual direction = rich dashboard.** Landing page gets stat tiles and visual
   punch; the reader's reading experience stays calm and untouched.
4. **Scope = full pass.** Shared primitives + landing + review + quiz + upload +
   reader chrome fixes + Arial→Geist fix.
5. **UI layer = hand-rolled `components/ui/`.** Small typed React primitives with
   raw Tailwind inside, tokens extended in `globals.css`. No shadcn/Radix, no CSS
   class-based system.

## 1. Foundation

### Tokens (`app/globals.css`)

- Fix `globals.css:91`: body font-family `Arial, Helvetica` → `var(--font-sans)`.
  The reading column is unaffected (it opts into `--font-serif` explicitly).
- Add CSS variables, each with light and dark values, exposed via `@theme inline`:
  - `--surface-raised` — card fill, slightly lifted from `--background`
  - `--accent-soft` — tinted panel background derived from `--accent`
  - `--status-good`, `--status-warning`, `--status-serious` + `-soft` fill variants
- All new color values are validated with the dataviz skill's
  `scripts/validate_palette.js` against BOTH surfaces (`--mode light` and
  `--mode dark`) before shipping. Computed, not eyeballed. Status colors are
  reserved for state, never decorative reuse.

### Primitives (`components/ui/`)

Seven components, raw Tailwind inside, typed props, no new deps:

| Component | Variants / notes |
|---|---|
| `Button` | primary / secondary / ghost / danger; sm / md |
| `Card` | plain / tinted / interactive (link wrapper) |
| `Badge` | filled status pill; ALWAYS icon + label, never color alone |
| `StatTile` | big number + label + optional href (dataviz hero-number spec: number wears text tokens, not series color) |
| `ProgressBar` | thin bar, `role="progressbar"` + `aria-valuenow` |
| `Skeleton` | shimmer placeholder; static under `prefers-reduced-motion` |
| `EmptyState` | icon + message + optional CTA |

All existing surfaces migrate onto these; the copy-pasted
`bg-black … dark:bg-white dark:text-black` button styling is deleted everywhere.

## 2. Landing page (`app/page.tsx` rework)

Layout, top to bottom:

1. **SiteHeader** — gains `ThemeToggle` (currently reader-only) and keeps `DueBadge`.
   Border fixed to the `border-border` token.
2. **Stat tile row** (3 tiles): Cards due (→ `/review`), Quizzes to take (→ quiz
   panel anchor), Course progress (% of continue-course, from
   `lib/dashboard/continue.ts` helpers). `backlog_warning` from review summary
   renders as a warning Badge under the Cards-due tile.
3. **Hero row**: Continue-reading card (2/3 width — course title, chapter,
   ProgressBar, Continue button) + Start-review card (1/3 width, accent-soft tint,
   per-course due counts from the summary).
4. **Study next** — existing logic, restyled as Cards with reason Badges.
5. **Quizzes to take** — new panel (see §3).
6. **Your courses** — grid of Cards: filled status Badge (replacing text-color
   StatusBadge), ProgressBar for read progress, existing SSE ingest states and
   per-asset failure expansion restyled but functionally unchanged.
7. **Learning science** — collapsible section at the bottom (see §4).

Data flow: one parallel fetch pass on mount — `listCourses` + `getReviewSummary` +
quiz derivation fetches, via the generated client only. **Per-panel failure
isolation**: each panel owns a panel-level `ErrorBanner`; one failed call never
blanks the page. Each panel shows `Skeleton` while loading.

Empty state (no courses): keep the existing full-width drag-drop zone, restyled on
`EmptyState`.

Responsive: tile row collapses 3→1 columns below `sm`; hero row stacks below `md`.

## 3. "Quizzes to take" derivation

- New pure function in `lib/dashboard/quizzes.ts`:
  `deriveQuizItems(courses, chaptersByCourse) → QuizItem[]` where a chapter
  qualifies if `test_stats.attempts === 0` (reason: "Not attempted") or
  `test_stats.best_score` below 70% of the maximum score (reason: "Retake
  suggested"). The threshold is expressed against the field's actual scale — the
  implementation first confirms from `schema.d.ts`/backend whether `best_score`
  is 0–100 or 0–1 and encodes the 70% cutoff accordingly. Pure = unit-testable
  without mocks.
- Dashboard fetches `listChapters(courseId)` for ready courses, capped at the 6
  most recently active courses (ordered by `progress.updated_at`, falling back to
  course creation order), in parallel. Top 5 derived items render, each
  linking to that chapter's test page. Same laptop-scale fan-out pattern
  StudyNextList already uses.
- The "Quizzes to take" stat tile shows the total derived count.

## 4. Videos section

- Curated static list in `lib/dashboard/videos.ts`: `{ videoId, title, blurb }[]`,
  4–6 videos covering spaced repetition and the learning-styles myth (e.g.
  Veritasium's learning-styles video plus spaced-repetition explainers).
  **Video IDs are verified at implementation time via web search** — none are
  written from memory. Deterministic static data; no API, no LLM.
- Rendering: `https://www.youtube-nocookie.com/embed/{id}`, `loading="lazy"`,
  fixed 16:9 aspect boxes, one `title` attribute per iframe, 2–3 column grid.
- Placement: bottom of the landing page under a collapsible "Learning science"
  header; collapsed/expanded state persisted in localStorage
  (`smv2.dashboard.videos`) following the existing localStorage key conventions.
  Bottom placement + lazy loading means zero YouTube traffic unless scrolled into
  view — "there if they want it".

## 5. Review surface (`app/review/page.tsx`)

- Grade buttons color-coded: Again = `--status-serious`, Hard = `--status-warning`,
  Good = `--status-good`, Easy = accent. Soft-filled backgrounds, label + icon
  (not color alone), existing keyboard hints unchanged.
- Card face rendered on the `Card` primitive; `Skeleton` while the queue loads;
  "All caught up" `EmptyState` when the queue is empty.
- Session-resume banner and all SRS logic unchanged.

## 6. Quiz surfaces

- `TestAttemptClient`: "Question N of M" + `ProgressBar`; answer options become
  selectable card rows; results screen gets a score `StatTile` hero and
  per-question `Card`s (✓/✗ + explanation as today).
- `ChapterTestClient`: mastery bar → `ProgressBar`; test history on `Card`s.
- Grading/redaction logic untouched.

## 7. Upload flow + reader chrome

- `UploadFlow` modal restyled on primitives, with a step indicator for its state
  machine (title → upload → ingest). `OutlineConfirmation` inherits Button/Card.
- Reader: reading experience (serif column, typography controls, keyboard nav,
  chevrons) untouched. TopBar decluttered: Edit outline / Generate all lessons /
  Quizzes fold into a single "⋯" overflow menu below the `lg` breakpoint; at `lg`+
  the current layout stands. Overflow menu reuses the existing
  `useDismissOnOutsideOrEscape` + `useDialogFocus` hook patterns.

## 8. Errors and updates (unchanged model)

- All fetches through `lib/api/client.ts` (generated client). `ErrorBanner` remains
  the only error surface; `err.status`-based retry affordance preserved.
- `reviewBus` + SSE (`useJobEvents`) keep DueBadge and stat tiles fresh after
  grading/generation. No polling introduced.

## 9. Testing

- Vitest + Testing Library, matching the existing `__tests__/` one-file-per-surface
  pattern:
  - `components/ui/` primitive render/variant tests (Badge never color-only,
    ProgressBar aria attributes, Skeleton reduced-motion).
  - `deriveQuizItems` pure-function unit tests (zero attempts, low score, boundary
    at 70, empty inputs).
  - Landing panel tests with mocked client: per-panel error isolation, skeleton →
    content, stat tile values.
  - Video section: renders `youtube-nocookie.com` iframes with `loading="lazy"`
    and titles; collapse state persists.
- Palette validator run for new tokens in both modes; results noted in the PR.
- Gate: full `./build.sh` from `smv2/` (typecheck + tests + build). Nothing less
  counts as done.

## Out of scope (explicit)

- Backend changes of any kind (no new endpoints, no migrations).
- Quiz scheduling ("due" stays derived, not scheduled).
- Mobile reader relayout beyond the TopBar overflow menu.
- New dependencies (no component libraries, no icon packages — inline SVG/emoji
  glyphs only).
- Prompt/LLM-layer changes.

## Implementation notes

- Work happens under `smv2/frontend` exclusively; `smv2-frontend-feature` skill
  governs procedure. No `openapi.json` / `schema.d.ts` regeneration needed (no
  API shape changes).
- Suggested phasing for the implementation plan: (1) tokens + Arial fix +
  primitives with tests, (2) landing page, (3) review/quiz surfaces, (4) upload +
  reader chrome, (5) videos + final gate.
