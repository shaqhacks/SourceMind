# Plan: UI redesign — "Organic" design system (2026-07-26)

Source of truth: `smv2/docs/design-frontend/Educational platform UI redesign/design_handoff_sourcemind_redesign/`
(README.md is the handoff; `designs/*.dc.html` are high-fidelity mocks; `designs/ds/organic.css`
+ `designs/ds/theme.css` are the token layer). Mocks are prototypes to recreate with
Tailwind against the app's own conventions — never copy their runtime (`support.js`).

## Scope decisions (user-confirmed 2026-07-26)

- Redesign is built **on top of the uncommitted highlights/notes work** on
  `smv2-highlights-backend` — no checkpoint commit first, per user choice.
- **All 9 screens.** Skill Map + Competency detail render from a typed placeholder
  module (`lib/skills/placeholder.ts`) visibly tagged "sample data" until the
  prereq-graph backend (approved at office hours 2026-07-26: PrereqConcept/Edge/Link,
  mastery map first) lands. No fake API calls — the mock lives client-side only.

## Token strategy

Keep the existing semantic variable names in `app/globals.css` (`--background`,
`--foreground`, `--muted-foreground`, `--border`, `--accent`, `--surface-raised`,
`--accent-soft`, `--status-*`) and retune their values to the handoff palette, so
every existing Tailwind utility re-skins without per-component edits. Additions:

| New token | Value (light) | From |
|---|---|---|
| `--divider` | 14% ink color-mix | theme.css `--color-divider` — hairlines; `--border` becomes the 24% control border |
| `--accent-{100..900}` | terracotta ramp | organic.css |
| `--sage`, `--sage-{100..900}` | accent-2 ramp (renamed for markup readability) | organic.css |
| `--neutral-{100..900}` | neutral ramp | theme.css |
| `--radius-sm/md/lg` = 4/8/12px | theme.css "solidity pass" | overrides Tailwind rounded-sm/md/lg |
| `--elev-sm/md/lg` → `--shadow-sm/md/lg` theme keys | theme.css | per-theme shadow values |
| `--font-heading` (Caprasimo 400), `--font-sans` → Figtree | via next/font/google, self-hosted (no Google @import) |

Dark theme: full inverted ramps from theme.css under the existing
`[data-theme="dark"]` convention + `prefers-color-scheme` fallback block; the
no-FOUC script in `app/layout.tsx` is untouched.

Deliberate deviations from the mock CSS (each is a call, not an oversight):

1. **`--status-serious` stays red.** The design system has no error color
   (terracotta = "attention"); collapsing errors into the warning hue would make
   ErrorBanner indistinguishable from due-count tags. Kept as-is, to revisit.
2. **Muted text uses ramp steps, not 55% opacity mixes.** organic.css's
   `.text-muted` (55% ink) is ~3.6:1 — below WCAG AA for small text. We use
   neutral-700 (light) / neutral-600 (dark), ≈5.5:1, visually equivalent.
3. **localStorage keys**: reuse existing `smv2.*` keys/hooks (`useTheme`,
   `useSidebarCollapsed`), not the prototypes' `sm.theme`/`sm.sidebar`.
4. **Icons**: Lucide (`lucide-react`, new dep) at stroke-width 2.75 per the
   handoff's stated convention, replacing the mocks' text glyphs.
5. **`--highlight-*` tokens unchanged** — they belong to the in-flight
   highlights/notes feature, not the brand layer.
6. **Border-only affordances retire.** Design secondaries are surface-filled with
   a 24% ink border; the old `--border`'s documented 3:1 border-only guarantee no
   longer applies — controls get fill+border together per the mock.

## Phases (task list ids)

1. Plan doc + tokens + fonts (`globals.css`, `layout.tsx`) — whole app re-skins.
2. App shell: collapsible 260px sidebar (nav Home/Flashcards/Tests, courses,
   drop target, LLM usage footer) + new header. Restyle `components/ui/*` primitives.
3. Home = daily study plan (`app/page.tsx`, `components/dashboard/*`).
4. Reader restyle (contents panel, 720px column, Chat/Cards/Notes right tabs) —
   preserves all shortcuts/progress-sync/popovers and the uncommitted notes work.
5. `/flashcards` (new route, existing cards endpoints).
6. Review session restyle (grade buttons show per-grade next interval).
7. `/tests` (new route) + quiz attempt restyle.
8. New Course dialog over UploadFlow (+ "Start a new course" copy).
9. Skill Map + Competency detail on `lib/skills/placeholder.ts`.
10. Tests updated/added → `npm run lint` → full `./build.sh` gate.

Verification per phase: `npm run typecheck` + targeted `npm test -- --run`;
final gate is `smv2/build.sh` (CI-identical).

## Build-time deviations (recorded as the screens landed, 2026-07-26)

- **Review interval preview became real, not mocked**: `ReviewQueueCardOut`
  gained `interval_days`/`ease`/`reps` (backend schemas + srs_service, no DB
  change); `lib/review/intervalPreview.ts` mirrors `schedule_next`'s non-Again
  branches with a unit test pinned to the backend's math.
- **Outline confirmation reinstated** in the Start-a-new-course dialog —
  ADR-026 supersedes ADR-014 (upload-flow point only).
- **Data honesty over mock fidelity**, applied consistently: no retention bars
  (`CardOut` has no grade/scheduling fields — table shows real `origin`); no
  "Seen N times / Last grade" badges; no per-day "This week" history; no
  fabricated cost estimates for card/test generation; sidebar course cards show
  counts, not a progress bar; quiz header shows date, not attempt ordinal;
  reader shows no "read" checkmarks (nothing records read-state) and no card
  counts on the CTA. Each omission has a code comment at the site.
- **Two-row chrome on reader/review/quiz**: global SiteHeader stays; each route
  renders its own slim control row beneath (mock shows one row). Revisit if a
  header-slot mechanism ever lands.
- **Reader right panel not unified into Chat/Cards/Notes tabs** — Chat and
  Notes remain two exclusive drawers (their `role="complementary"` names are
  test contracts); cards stay inline. Restyled in place; unification deferred.
- **Shared sidebar-collapse key across app sidebar and reader Contents** is
  by design: the reader route has no app sidebar, so the header ☰ toggles
  Contents there, matching the mock (whose prototypes also share one key).
- **Skill screens ship on `lib/skills/placeholder.ts`** (typed sample data,
  visible "Sample data" badges) until the PrereqConcept/Edge/Link backend
  (approved 2026-07-26 office hours) lands; competency stat tiles that have
  zero backing fields are suffixed "(sample)".
- Status circles 18px (mock markup) over README prose's 22px; reading column
  uses the body face per the mock (serif remains available via typography
  prefs); `components/chapter/*` (legacy chapter-test surface) inherits the
  reskin via primitives but was not redesigned.
