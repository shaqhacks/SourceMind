# Handoff: SourceMind UI Redesign

## Overview
A full UI redesign of SourceMind v2 (the local-first course-workbook app in the `smv2` repo: FastAPI/SQLite backend + Next.js App Router frontend). The redesign replaces the current utilitarian UI with a professional study-app experience: a guided daily study plan, a collapsible app sidebar, top-level Flashcards and Tests views, dark mode, and a **new feature** — a per-course competency/skill map with prerequisite diagnosis ("you're failing multiplication because addition is weak") and clickable competency detail pages.

## About the Design Files
The files in `designs/` are **design references created in HTML** — prototypes showing the intended look and behavior, not production code to copy. The task is to **recreate these designs in the existing `smv2/frontend` Next.js + TypeScript + Tailwind codebase**, using its established patterns: the generated API client (`lib/api/client`), the single ErrorBanner, the shared Chat component, existing hooks (`useTheme`, `useJobEvents`, `useKeyboardShortcuts`, etc.), and Tailwind theme tokens in `app/globals.css`.

Each `.dc.html` opens directly in a browser. Ignore `support.js` and the `<x-dc>` wrapper — they are the prototype runtime. Read the inline styles and the two CSS files for exact values. The sidebar/theme toggles at the top of each page work in the prototypes (state in `localStorage`: `sm.theme`, `sm.sidebar`).

## Fidelity
**High-fidelity.** Colors, type, spacing, radii and copy are final intent. Recreate pixel-perfectly with Tailwind against the new token set (below). Sample data (course "Welcome to SourceMind", 12 cards due, skill names) is placeholder — wire to real API data.

## Design Tokens
Defined in `designs/ds/organic.css` (base system) overridden by `designs/ds/theme.css` (neutral ground + dark theme). Port these into `app/globals.css` as CSS variables, replacing the current `--background`/`--accent` set. Both files use `color-mix()`; the app already targets modern browsers.

Light theme:
- Ground: `--color-bg #fafaf7`, surface `#efeeea`, text `#1e1e1c`, divider `color-mix(in srgb, #1e1e1c 14%, transparent)`
- Accent (terracotta): base `#c67139`; ramp 100–900: `#fff2eb #ffe1d0 #ffc6a5 #f6a06b #d67f48 #b2622d #8c491a #643312 #402310`
- Accent-2 (sage): base `#7a8a5e`; ramp 100–900: `#f0fae1 #e1eecc #ccdbb2 #aebf92 #8fa073 #728157 #56633f #3d472b #272e1b`
- Neutrals 100–900: `#f5f5f2 #e9e9e4 #d9d9d2 #bcbcb3 #9d9d94 #7e7e76 #60605a #444440 #2c2c29`

Dark theme (`[data-theme="dark"]`, matching the app's existing manual-override convention):
- Ground `#16181d`, surface `#21242b`, text `#ecedee`; accent base `#e08a52`; full inverted ramps in `theme.css`

Type:
- Headings: **Caprasimo** 400 (`--font-heading`) — page titles, stat numbers, card questions
- Body/UI: **Figtree** 400/600/700 (`--font-body`), 15px base, 1.55 line-height
- Both load from Google Fonts (see `organic.css` @import)

Shape & elevation:
- Radii: controls (buttons/inputs/tags/seg) 6–8px; cards/dialogs 12px; progress bars & avatars 999px
- Cards: `background: var(--color-surface); border: 1px solid var(--color-divider); border-radius: 12px`
- Shadows: sm `0 1px 2px` @10% ink, md `0 3px 10px` @12%, lg `0 12px 32px` @18% (dark theme: black at 50–60%)
- Buttons: primary = solid accent fill, text = bg color; secondary = surface fill + 24%-ink border; ghost = accent text, transparent

Semantic color use: sage = good/solid/met; terracotta = attention/due/struggling (deeper ramp steps for text); neutrals for locked/inactive. Status tags: `tag-accent-2` (sage tint), `tag-accent` (terracotta tint), `tag-neutral`.

## App Shell (all screens)
- **Header** (all pages): 12×20px padding, bottom divider. Left: ☰ sidebar toggle (36px icon button), brand "SourceMind" in Caprasimo 20px accent color. Right: "12 cards due" accent tag, "3-day streak" sage tag (Home only), theme toggle (☾/☀ icon button), 34px round avatar (sage-300 bg).
- **Sidebar** (collapsible, 260px, right divider, persists via localStorage; replaces the current top-tab-less layout — suggest reworking `AppShell.tsx` + `SiteHeader.tsx`):
  - "+ Start new course" primary block button (opens the New Course flow)
  - Nav: Home, Flashcards (with due-count tag), Tests — active item gets surface bg + shadow-sm + accent-700 text, 8px radius, 9×14px padding
  - "Your courses" section: one card per course — title (links to reader), "3 chapters · 12 due" meta, 5px progress bar, and per-course sub-links **Open · Skill map** (skill maps are per-course, NOT global nav)
  - Dashed "Drop a PDF here to add one" drop target
  - Footer: "LLM usage: 6 calls · $0.14"
- **Dark mode**: `data-theme="dark"` on `<html>`; reuse the app's existing `useTheme` hook. The prototype's ☾/☀ button maps to the existing System/Light/Dark preference.

## Screens / Views

### 1. Home — `Redesign - Home.dc.html` (route `/`)
Purpose: the daily loop in one glance.
- Header row: date + "~12 min planned" muted line; H1 "Today's study plan" (Caprasimo 34px); right-aligned stat trio (Caprasimo 24px numbers: course progress %, cards this week, avg quiz score)
- Grid `1fr 340px`, 24px gap:
  - Left: three numbered task cards (row layout, 20×24px padding): 44px numbered circle (accent-200/sage-200/neutral-200 fills), bold 16px title, 13px muted meta, action button on the right (primary "Resume", secondary "Start review"/"Retake test"). Task 1 includes a 6px progress bar.
  - Right: **Skill snapshot** card — three labeled 6px mastery bars (sage-500 solid / accent-400 mid / accent-600 struggling) with numeric scores, "Full map →" ghost link, and a diagnosis callout (accent-100 bg, 12px radius): "Why you're stuck: Cost estimation builds on token counting…" + primary CTA "Review the prerequisite". Below: **This week** card — 7 day-tiles (32px, sage fills for done days, dashed accent outline for today) + streak nudge line.
- Data: courses via `listCourses`, review summary via `getReviewSummary`, study-next via `getStudyNext`; skill snapshot needs the new competency API (below).

### 2. Reader — `Redesign - Reader.dc.html` (route `/course/[courseId]`)
- Header variant: ☰ toggles the **Contents** panel; breadcrumb "Welcome to SourceMind / Chapter 2 · …"; Source/Pages/Lesson segmented control; "Edit outline" and "Aa" secondary buttons; theme toggle.
- Contents panel (280px): one row per chapter — 22px status circle (✓ sage fill = read, accent ring = current, neutral ring = unread), title, score tag; current row gets surface bg + shadow + bold. Bottom-pinned "Chapter progress" callout (sage-100 bg) with bar + "38% read · 8 cards due".
- Reading column: max-width 720px centered, 44×32px padding; muted "Chapter 2 · p.3–4"; H2 30px; body 17px/1.7 (typography controls still apply); highlights use accent-200 `<mark>`.
- Below body: flashcards CTA card (row: count + meta, "Review 8 due" primary, "Generate more" secondary), then prev/next ghost links split left/right over a top divider.
- Right panel (340px, left divider): segmented **Chat / Cards / Notes** tabs; chat transcript (user bubbles accent-100 right-aligned, assistant bubbles surface left-aligned, citation as outline tag "Ch.2 · p.4" — navigates via section_id per existing convention), tip callout (sage-100); composer input + primary Send pinned bottom.
- Keep all existing reader behavior: keyboard shortcuts, progress sync, selection popovers (restyle popovers with card tokens).

### 3. Flashcards — `Redesign - Flashcards.dc.html` (new route `/flashcards`)
- H1 + "12 due now · 26 cards total" subtitle; "Review all due (12)" primary button top-right
- Deck grid (3-up): per-chapter cards — kicker "Chapter N", Caprasimo title, "N due" accent tag + "N cards" neutral tag, retention bar, meta line, Review (primary) + Browse (secondary) buttons. Chapters with no cards render as dashed-border generate cards with cost estimate ("~$0.02").
- "All cards — Chapter 2" table (reuse `.table` pattern): Front / Next review / Retention / Edit; due rows use accent tag, retention colored by last grade (Hard = accent-700, Good/Easy = sage-700).

### 4. Review session — `Redesign - Review.dc.html` (route `/review`)
- Minimal header: ← back, brand, "Review session · course" label, theme toggle, "End session" secondary
- Centered 760px column: 8px progress bar + "3 of 12"; big card (elev-md, 40×44px padding, min-height 320px): kicker "Chapter 2 · Spaced repetition", question in Caprasimo 24px, divider, answer 17px (answer hidden until reveal — existing space-to-reveal flow), footer row of tags ("Seen 4 times", "Last grade: Hard") + "Open in chapter →" ghost
- Grade row: 4 equal buttons (accent-200 Again / accent-100 Hard / sage-200 Good / sage-300 Easy), each with sub-label "1 · <10 min", "2 · 2 days", "3 · 5 days", "4 · 12 days" — **show the next interval per grade** (compute from scheduler)
- Keyboard hint line with `<kbd>` chips. Preserve existing session resume/localStorage behavior.

### 5. Tests — `Redesign - Tests.dc.html` (new route `/tests`)
- Per-chapter test cards: kicker, verdict line ("Best score 60% — below your 80% target"), attempts meta, 54px conic-gradient score ring (accent <80%, sage ≥80%), Retake button. Weak chapters expand with a "Missed last time" section listing missed questions + "Review answer" ghost buttons. Untested chapters = dashed generate card with cost.
- Right rail: **Score history** card (simple bar chart of attempts, accent → sage as scores improve; "Missed questions are added to your flashcards automatically" note) and **Diagnosis** card linking misses to a competency + "Drill …" primary CTA.

### 6. Quiz attempt — `Redesign - Quiz.dc.html` (route `/course/[courseId]/test/[attemptId]`)
- Minimal header (← back, "Chapter 1 test · attempt 3", Save & exit)
- 760px column: progress bar + "Question 2 of 5"; question card (elev-md): kicker = competency name, Caprasimo 22px question, 4 numbered choice rows (1px divider border, bg ground; selected = 1.5px accent border + accent-100 bg), footer "← Previous" ghost / "Next question" primary
- Keep existing 1–4 / Enter shortcuts and post-submit review flow (style results with the same card + tag vocabulary).

### 7. Skill map — `Redesign - Skill Map.dc.html` (new route `/course/[courseId]/skills`)
**Per-course** (breadcrumb "Course / Skill map", title "Skill map — <course>"; reached from the sidebar course card, Home snapshot, and Tests diagnosis).
- Layout is **data-driven** (see the prototype's logic class for the exact algorithm): N vertical lanes ("Level 1 · Foundations" → "Level N"), uniform 260×118px skill cards on aligned 170px-pitch rows, 370px lane pitch, vertical divider lines between lanes, horizontal scroll if lanes overflow.
- Edges drawn in an SVG underlay: straight lines when source/target share a row, cubic curves otherwise; multiple edges into one node fan out ±7px; solid sage = prerequisite met, dashed terracotta = weak prerequisite (fix first); 4px dot at each target. Legend below.
- Skill card: name (bold 14px), status tag (Solid = sage / Growing = neutral / Struggling = accent + 1.5px accent border on the card / Locked = neutral with "Unlocks at …" note), mastery bar, one-line note. **Whole card links to the competency detail page.** Hover: shadow-md + 1px lift.
- Bottom "Recommended fix" card (elev-md): root-cause sentence + "Start 4-min fix" primary + "See what to review" secondary.
- "By prerequisite / By chapter" segmented toggle top-right (by-chapter view: same cards grouped under chapter headings — not prototyped, optional v2).

### 8. Competency detail — `Redesign - Competency.dc.html` (new route `/course/[courseId]/skills/[skillId]`)
- Breadcrumb Course / Skill map / <skill>; H1 + "Struggling · 31 mastery" tag; blocked-skills sentence
- Stat trio: Mastery (number + bar), Cards on this skill, Quiz record
- **"Where this skill is taught — review these"**: one card per chapter/section teaching the competency — kicker "Chapter 2 · section 2.2", bold title, relevance blurb + read time, "Most relevant" tag on the top one, Re-read button (→ reader at that section); most-relevant card also has a footer row ("You highlighted this section once · 2 missed questions cite it" + "Review its 3 cards" ghost)
- "Questions you missed on this skill": cards quoting the question, your answer vs correct, source test + recency
- "Fix plan" card: sequenced recommendation + "Start with 2.2" primary + "Drill 5 cards" secondary

### 9. New course — `Redesign - New Course.dc.html` (dialog over any page)
- Dialog (620px, 12px radius, elev-lg) titled "Start a new course" — replaces "Upload PDF" copy everywhere
- 3-step indicator: Upload (✓ sage) — Confirm outline (active, accent) — Start reading
- Uploaded-file row ("Uploaded · 214 pages" sage tag), Course title input, detected-outline list (scrollable, rows: "1 · Describing Data", page range, Rename/Split ghost buttons; staged merge shown with accent-100 row bg + "merging with 4" tag + Undo), reassurance note about re-editing later, Cancel / "Accept outline & start reading" actions
- Maps onto the existing UploadFlow state machine; outline confirmation returns as an explicit step (it currently lives only in the reader).

## Interactions & Behavior
- Sidebar toggle and theme toggle persist (`localStorage`), applied pre-paint (reuse the app's no-FOUC pattern)
- All hover states: buttons per the token layer (primary → accent-600; secondary → 7% ink tint); interactive cards get shadow-md; keep `:focus-visible` 2px accent outline
- Navigation flows: task cards → reader/review/quiz; skill cards → competency page; competency actions → reader section / review session scoped to that skill's cards; Tests diagnosis → competency page
- Preserve every existing keyboard shortcut (reader j/k/s/c/o/?, review space/1–4, quiz 1–4/Enter) and the existing SSE job-progress patterns for generation buttons (generate cards/test buttons show the usual progress line while a job runs)

## State Management & Data
Existing endpoints cover everything except competencies. New backend work implied by the design:
- **Competency model**: per course — id, name, level (int), prerequisite ids, mastery score (derived from card grades + quiz results), status (solid/growing/struggling/locked), links to sections (where taught) and to cards/questions (evidence)
- Endpoints: `GET /courses/{id}/skills` (map: nodes + edges + statuses), `GET /skills/{id}` (detail: sections, missed questions, fix plan), and tagging of generated quiz questions/cards with a skill id at generation time
- Diagnosis rule of thumb shown in the UI: a skill is "blocked" when a prerequisite's mastery is below ~60; misses that cite prerequisite material drive the "root cause" callout

## Assets
No image assets. Fonts from Google Fonts (Caprasimo, Figtree). Icons in the prototypes are text glyphs (☰ ☾ ✓ ← →); the design system's convention is Lucide icons at stroke-width 2.75 — substitute Lucide equivalents (menu, moon/sun, check, arrow-left, arrow-right) in implementation.

## Files
- `designs/Redesign - Home.dc.html` — dashboard / study plan
- `designs/Redesign - Reader.dc.html` — course reader with chat panel
- `designs/Redesign - Flashcards.dc.html` — flashcards tab
- `designs/Redesign - Review.dc.html` — review session
- `designs/Redesign - Tests.dc.html` — tests tab
- `designs/Redesign - Quiz.dc.html` — quiz attempt
- `designs/Redesign - Skill Map.dc.html` — per-course skill map (data-driven layout algorithm in its `<script>`)
- `designs/Redesign - Competency.dc.html` — competency detail
- `designs/Redesign - New Course.dc.html` — start-new-course dialog
- `designs/ds/organic.css` — base design-system tokens + component classes
- `designs/ds/theme.css` — neutral-ground override + dark theme (load after organic.css)
- `designs/support.js` — prototype runtime only; ignore
