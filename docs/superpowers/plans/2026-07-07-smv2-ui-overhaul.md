# SMV2 UI Overhaul + Rich Landing Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rich-dashboard landing page (stat tiles, quizzes-to-take panel, learning-science videos) plus a full visual polish pass on shared primitives, review, quiz, upload, and reader chrome.

**Architecture:** Hand-rolled `components/ui/` primitives on top of new CSS-variable tokens in `globals.css`; existing surfaces migrate onto them. All data from the existing generated API client — zero backend changes. Spec: `docs/superpowers/specs/2026-07-07-smv2-ui-overhaul-design.md`.

**Tech Stack:** Next.js 16 (App Router), TypeScript, Tailwind v4 (CSS-first), Vitest + Testing Library.

## Global Constraints

- All work under `smv2/frontend`. NEVER touch repo-root `frontend/` (that is v1).
- Zero new dependencies. Zero backend changes. Never hand-edit `lib/api/schema.d.ts` or `smv2/openapi.json`.
- All fetches via `@/lib/api/client` (generated client). Errors surface via `@/components/ErrorBanner`.
- **Next.js 16 caveat (`smv2/frontend/AGENTS.md`):** APIs may differ from training data. Before using any Next API not already used in this codebase, read the guide in `node_modules/next/dist/docs/`. Prefer copying in-repo patterns.
- Commands run from `smv2/frontend` unless stated: `npm test -- --run`, `npm run typecheck`, `npm run lint`. Full gate from `smv2/`: `./build.sh`.
- Commit after every task. Conventional Commits, scope `smv2`, e.g. `feat(smv2): ui primitives`. Trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Dark mode: use `dark:` utilities (they follow `data-theme` via the `@custom-variant` in `globals.css`) or theme-switching CSS vars. Never `@media` queries directly in components.
- Accessibility floor (do not regress): `:focus-visible` ring is global; keep every existing `aria-*`, `role`, keyboard handler intact when restyling.
- **Migration table** (applies wherever old patterns are met while editing a file):

| Old pattern | Replace with |
|---|---|
| `bg-black px-? py-? text-white dark:bg-white dark:text-black` button | `<Button variant="primary" size="sm|md">` |
| `border border-border px-? py-?` button | `<Button variant="secondary" size="sm|md">` |
| text-only red delete/confirm buttons | `<Button variant="danger" size="sm">` |
| `rounded-lg border border-border p-4` container | `<Card>` (add `variant="tinted"` where `bg-accent/5` was) |
| colored-text-only status span | `<Badge tone=...>` |
| bare "Loading…" `<p>` | `<Skeleton>` block matching the content's shape |

---

### Task 1: Tokens + Arial→Geist fix

**Files:**
- Modify: `smv2/frontend/app/globals.css`

**Interfaces:**
- Produces Tailwind utilities used by every later task: `bg-surface-raised`, `bg-accent-soft`, `text-status-good|warning|serious`, `bg-status-good-soft|warning-soft|serious-soft`.

- [ ] **Step 1: Edit body font (globals.css:88-92)**

```css
body {
  background: var(--background);
  color: var(--foreground);
  font-family: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
}
```

- [ ] **Step 2: Add tokens.** Append inside `:root` (after `--accent: #2563eb;`) AND inside `:root[data-theme="light"]`:

```css
  --surface-raised: #f5f3ef;
  --accent-soft: #dbeafe;
  --status-good: #15803d;
  --status-good-soft: #dcfce7;
  --status-warning: #a16207;
  --status-warning-soft: #fef3c7;
  --status-serious: #b91c1c;
  --status-serious-soft: #fee2e2;
```

Inside the `@media (prefers-color-scheme: dark)` `:root` block AND `:root[data-theme="dark"]`:

```css
  --surface-raised: #1c2027;
  --accent-soft: #1e2a45;
  --status-good: #4ade80;
  --status-good-soft: #12271a;
  --status-warning: #fbbf24;
  --status-warning-soft: #2b2412;
  --status-serious: #f87171;
  --status-serious-soft: #2f1a1a;
```

Inside `@theme inline`:

```css
  --color-surface-raised: var(--surface-raised);
  --color-accent-soft: var(--accent-soft);
  --color-status-good: var(--status-good);
  --color-status-good-soft: var(--status-good-soft);
  --color-status-warning: var(--status-warning);
  --color-status-warning-soft: var(--status-warning-soft);
  --color-status-serious: var(--status-serious);
  --color-status-serious-soft: var(--status-serious-soft);
```

- [ ] **Step 3: Validate palette — run, don't eyeball.** Dataviz validator (base dir `/private/tmp/claude-501/bundled-skills/2.1.201/81997d243c89323b1b5daba46fc20269/dataviz`):

```bash
node <dataviz-base>/scripts/validate_palette.js "#15803d,#a16207,#b91c1c" --mode light --surface "#fdfcfb"
node <dataviz-base>/scripts/validate_palette.js "#4ade80,#fbbf24,#f87171" --mode dark --surface "#15181d"
```

Also check each strong status color against its own `-soft` fill (badge text sits on it). Expected: PASS. On FAIL: darken (light mode) / lighten (dark mode) the failing hex one Tailwind step (e.g. green-700→green-800) and re-run until PASS. Record final values + validator output in the commit message body.

- [ ] **Step 4: Verify nothing broke**

Run: `npm run typecheck && npm test -- --run`
Expected: PASS (no component references these tokens yet).

- [ ] **Step 5: Commit** — `style(smv2): design tokens + restore Geist body font`

---

### Task 2: Button, Card, Badge primitives

**Files:**
- Create: `smv2/frontend/components/ui/Button.tsx`, `components/ui/Card.tsx`, `components/ui/Badge.tsx`
- Test: `smv2/frontend/__tests__/ui-primitives.test.tsx`

**Interfaces:**
- Produces: `Button({variant?: "primary"|"secondary"|"ghost"|"danger", size?: "sm"|"md", className?, ...ButtonHTMLAttributes})`; `Card({variant?: "plain"|"tinted", interactive?: boolean, className?, children})` — a `div`; `Badge({tone: "good"|"warning"|"serious"|"neutral"|"accent", children, icon?})` — icon defaults per tone, never color-alone.

- [ ] **Step 1: Write failing tests**

```tsx
// __tests__/ui-primitives.test.tsx
import { render, screen } from "@testing-library/react";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";

describe("Button", () => {
  it("renders primary variant with token classes", () => {
    render(<Button variant="primary">Save</Button>);
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn.className).toContain("bg-foreground");
    expect(btn.className).toContain("text-background");
  });
  it("defaults to secondary md and forwards props", () => {
    render(<Button disabled>Cancel</Button>);
    const btn = screen.getByRole("button", { name: "Cancel" });
    expect(btn).toBeDisabled();
    expect(btn.className).toContain("border-border");
  });
});

describe("Card", () => {
  it("tinted variant uses accent-soft", () => {
    const { container } = render(<Card variant="tinted">x</Card>);
    expect((container.firstChild as HTMLElement).className).toContain("bg-accent-soft");
  });
});

describe("Badge", () => {
  it("always renders a glyph beside the label (not color-alone)", () => {
    render(<Badge tone="good">Ready</Badge>);
    const badge = screen.getByText("Ready").closest("span")!;
    expect(badge.textContent!.length).toBeGreaterThan("Ready".length);
    expect(badge.className).toContain("bg-status-good-soft");
  });
});
```

- [ ] **Step 2: Run to verify fail** — `npm test -- --run __tests__/ui-primitives.test.tsx` → FAIL (modules not found).

- [ ] **Step 3: Implement**

```tsx
// components/ui/Button.tsx
import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-foreground text-background hover:opacity-90",
  secondary: "border border-border hover:bg-muted-foreground/10",
  ghost: "hover:bg-muted-foreground/10",
  danger: "border border-status-serious/40 text-status-serious hover:bg-status-serious-soft",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-2 py-1 text-xs",
  md: "px-4 py-2 text-sm",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export default function Button({
  variant = "secondary",
  size = "md",
  className = "",
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    />
  );
}
```

```tsx
// components/ui/Card.tsx
import type { HTMLAttributes } from "react";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "plain" | "tinted";
  /** Adds hover affordance when the card wraps/sits under a link. */
  interactive?: boolean;
}

export default function Card({
  variant = "plain",
  interactive = false,
  className = "",
  ...rest
}: CardProps) {
  const bg = variant === "tinted" ? "bg-accent-soft/60" : "bg-surface-raised";
  const hover = interactive ? "transition-colors hover:border-muted-foreground" : "";
  return (
    <div
      className={`rounded-lg border border-border p-4 ${bg} ${hover} ${className}`}
      {...rest}
    />
  );
}
```

```tsx
// components/ui/Badge.tsx
import type { ReactNode } from "react";

export type BadgeTone = "good" | "warning" | "serious" | "neutral" | "accent";

const TONES: Record<BadgeTone, { classes: string; glyph: string }> = {
  good: { classes: "bg-status-good-soft text-status-good", glyph: "✓" },
  warning: { classes: "bg-status-warning-soft text-status-warning", glyph: "⚠" },
  serious: { classes: "bg-status-serious-soft text-status-serious", glyph: "✕" },
  neutral: { classes: "bg-muted-foreground/10 text-muted-foreground", glyph: "•" },
  accent: { classes: "bg-accent-soft text-accent", glyph: "●" },
};

export interface BadgeProps {
  tone: BadgeTone;
  children: ReactNode;
  /** Override the default glyph; pass a string/element, never null — a badge is never color-alone. */
  icon?: ReactNode;
}

export default function Badge({ tone, children, icon }: BadgeProps) {
  const { classes, glyph } = TONES[tone];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      <span aria-hidden="true">{icon ?? glyph}</span>
      {children}
    </span>
  );
}
```

- [ ] **Step 4: Run tests** — `npm test -- --run __tests__/ui-primitives.test.tsx` → PASS. Then `npm run typecheck` → PASS.

- [ ] **Step 5: Commit** — `feat(smv2): Button/Card/Badge ui primitives`

---

### Task 3: StatTile, ProgressBar, Skeleton, EmptyState

**Files:**
- Create: `components/ui/StatTile.tsx`, `components/ui/ProgressBar.tsx`, `components/ui/Skeleton.tsx`, `components/ui/EmptyState.tsx`
- Test: append to `__tests__/ui-primitives.test.tsx`

**Interfaces:**
- Produces: `StatTile({value: string|number, label: string, href?: string, hint?: ReactNode})`; `ProgressBar({percent: number, label: string})` (label feeds `aria-label`); `Skeleton({className?})`; `EmptyState({icon?: string, title: string, body?: string, cta?: ReactNode})`.

- [ ] **Step 1: Write failing tests**

```tsx
import StatTile from "@/components/ui/StatTile";
import ProgressBar from "@/components/ui/ProgressBar";
import EmptyState from "@/components/ui/EmptyState";

describe("StatTile", () => {
  it("links when href given", () => {
    render(<StatTile value={12} label="Cards due" href="/review" />);
    expect(screen.getByRole("link", { name: /12.*Cards due/s })).toHaveAttribute("href", "/review");
  });
});

describe("ProgressBar", () => {
  it("exposes progressbar semantics and clamps", () => {
    render(<ProgressBar percent={140} label="Course progress" />);
    const bar = screen.getByRole("progressbar", { name: "Course progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "100");
  });
});

describe("EmptyState", () => {
  it("renders title, body and CTA", () => {
    render(<EmptyState title="All caught up" body="Nothing due." cta={<a href="/">Home</a>} />);
    expect(screen.getByText("All caught up")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to fail** — same command as Task 2, new tests FAIL.

- [ ] **Step 3: Implement**

```tsx
// components/ui/StatTile.tsx
import Link from "next/link";
import type { ReactNode } from "react";

export interface StatTileProps {
  value: string | number;
  label: string;
  href?: string;
  hint?: ReactNode;
}

/** Hero-number tile (dataviz spec): the number wears text tokens, never a series color. */
export default function StatTile({ value, label, hint, href }: StatTileProps) {
  const body = (
    <>
      <p className="text-3xl font-semibold tracking-tight">{value}</p>
      <p className="mt-1 text-sm text-muted-foreground">{label}</p>
      {hint ? <div className="mt-2">{hint}</div> : null}
    </>
  );
  const frame = "block rounded-lg border border-border bg-surface-raised p-4";
  return href ? (
    <Link href={href} className={`${frame} transition-colors hover:border-muted-foreground`}>
      {body}
    </Link>
  ) : (
    <div className={frame}>{body}</div>
  );
}
```

```tsx
// components/ui/ProgressBar.tsx
export interface ProgressBarProps {
  percent: number;
  label: string;
}

export default function ProgressBar({ percent, label }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      className="h-1.5 w-full overflow-hidden rounded-full bg-muted-foreground/15"
    >
      <div className="h-full rounded-full bg-accent" style={{ width: `${clamped}%` }} />
    </div>
  );
}
```

```tsx
// components/ui/Skeleton.tsx
/** animate-pulse is neutralized globally under prefers-reduced-motion (globals.css). */
export default function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-md bg-muted-foreground/15 ${className}`} />;
}
```

```tsx
// components/ui/EmptyState.tsx
import type { ReactNode } from "react";

export interface EmptyStateProps {
  icon?: string;
  title: string;
  body?: string;
  cta?: ReactNode;
}

export default function EmptyState({ icon, title, body, cta }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-10 text-center">
      {icon ? (
        <span aria-hidden="true" className="text-3xl">
          {icon}
        </span>
      ) : null}
      <p className="text-lg font-medium">{title}</p>
      {body ? <p className="text-sm text-muted-foreground">{body}</p> : null}
      {cta ? <div className="mt-2">{cta}</div> : null}
    </div>
  );
}
```

- [ ] **Step 4: Run tests + typecheck** → PASS.
- [ ] **Step 5: Commit** — `feat(smv2): StatTile/ProgressBar/Skeleton/EmptyState primitives`

---

### Task 4: deriveQuizItems

**Files:**
- Create: `lib/dashboard/quizzes.ts`
- Test: `__tests__/quizzes-derive.test.ts`

**Interfaces:**
- Consumes: `ChapterOut` from `@/lib/api/client`.
- Produces: `deriveQuizItems(entries: CourseChapters[]): QuizItem[]` and `QUIZ_RETAKE_THRESHOLD`; types below.

- [ ] **Step 1: Confirm `best_score` scale and `ChapterOut` field names.** Run:

```bash
grep -n "best_score" lib/api/schema.d.ts
grep -n "ChapterOut" -A 20 lib/api/schema.d.ts | head -40
```

Also check the producer: `grep -n "best_score" ../backend/app/services/*.py`. If scores are 0–1, set `QUIZ_RETAKE_THRESHOLD = 0.7`; if 0–100, `70`. Confirm chapter label/title field names and adjust the code below to the real names before writing it.

- [ ] **Step 2: Write failing tests**

```ts
// __tests__/quizzes-derive.test.ts
import { describe, expect, it } from "vitest";
import { deriveQuizItems, QUIZ_RETAKE_THRESHOLD } from "@/lib/dashboard/quizzes";

const chapter = (label: string, attempts: number, best: number | null) =>
  ({ chapter_label: label, title: `Ch ${label}`, test_stats: { attempts, best_score: best, latest_score: best } }) as never;

describe("deriveQuizItems", () => {
  it("flags never-attempted chapters", () => {
    const items = deriveQuizItems([
      { courseId: "c1", courseTitle: "T", chapters: [chapter("1", 0, null)] },
    ]);
    expect(items).toEqual([
      expect.objectContaining({ courseId: "c1", chapterLabel: "1", reason: "not_attempted" }),
    ]);
  });
  it("flags low best score, boundary exclusive", () => {
    const items = deriveQuizItems([
      {
        courseId: "c1",
        courseTitle: "T",
        chapters: [
          chapter("1", 2, QUIZ_RETAKE_THRESHOLD),      // at threshold: NOT flagged
          chapter("2", 2, QUIZ_RETAKE_THRESHOLD - 1),  // below: flagged
        ],
      },
    ]);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ chapterLabel: "2", reason: "retake" });
  });
  it("returns empty for empty input", () => {
    expect(deriveQuizItems([])).toEqual([]);
  });
});
```

(If Step 1 found a 0–1 scale, change `- 1` to `- 0.1`.)

- [ ] **Step 3: Run to fail**, then implement:

```ts
// lib/dashboard/quizzes.ts
/**
 * "Quizzes to take" is DERIVED, not scheduled (spec decision 1): a chapter
 * qualifies if it was never attempted or its best score is below the
 * threshold. Pure function — fetching stays in the panel component.
 */
import type { ChapterOut } from "@/lib/api/client";

export const QUIZ_RETAKE_THRESHOLD = 70; // adjust per Step 1 scale check

export interface CourseChapters {
  courseId: string;
  courseTitle: string;
  chapters: ChapterOut[];
}

export interface QuizItem {
  courseId: string;
  courseTitle: string;
  chapterLabel: string;
  chapterTitle: string;
  reason: "not_attempted" | "retake";
  bestScore: number | null;
}

export function deriveQuizItems(entries: CourseChapters[]): QuizItem[] {
  const items: QuizItem[] = [];
  for (const { courseId, courseTitle, chapters } of entries) {
    for (const ch of chapters) {
      const stats = ch.test_stats;
      if (!stats) continue;
      if (stats.attempts === 0) {
        items.push({ courseId, courseTitle, chapterLabel: ch.chapter_label, chapterTitle: ch.title, reason: "not_attempted", bestScore: null });
      } else if (stats.best_score != null && stats.best_score < QUIZ_RETAKE_THRESHOLD) {
        items.push({ courseId, courseTitle, chapterLabel: ch.chapter_label, chapterTitle: ch.title, reason: "retake", bestScore: stats.best_score });
      }
    }
  }
  // not_attempted first, then lowest score first — most actionable at top
  return items.sort((a, b) =>
    a.reason === b.reason ? (a.bestScore ?? -1) - (b.bestScore ?? -1) : a.reason === "not_attempted" ? -1 : 1,
  );
}
```

Adjust field access (`chapter_label`, `title`, `test_stats`) to the exact names Step 1 found.

- [ ] **Step 4: Run tests + typecheck** → PASS.
- [ ] **Step 5: Commit** — `feat(smv2): derive quizzes-to-take from chapter test stats`

---

### Task 5: Videos data + VideoSection

**Files:**
- Create: `lib/dashboard/videos.ts`, `components/dashboard/VideoSection.tsx`
- Test: `__tests__/video-section.test.tsx`

**Interfaces:**
- Produces: `LEARNING_VIDEOS: {videoId: string; title: string; blurb: string}[]`; `<VideoSection />` (no props).

- [ ] **Step 1: Verify video IDs via web search — NEVER from memory.** Find 4–6 videos: at least one on the learning-styles myth (Veritasium has one), 2–3 spaced-repetition/active-recall explainers from reputable channels. For each candidate, confirm the 11-char video ID by fetching `https://www.youtube.com/watch?v=<id>` (or oEmbed: `https://www.youtube.com/oembed?url=...&format=json`) and checking the returned title matches. Record `{videoId, title, blurb}` — blurb is one factual sentence you write.

- [ ] **Step 2: Write failing test**

```tsx
// __tests__/video-section.test.tsx
import { render, screen } from "@testing-library/react";
import VideoSection from "@/components/dashboard/VideoSection";
import { LEARNING_VIDEOS } from "@/lib/dashboard/videos";

describe("VideoSection", () => {
  beforeEach(() => localStorage.clear());

  it("renders privacy-enhanced lazy iframes for every video", () => {
    render(<VideoSection />);
    const frames = screen.getAllByTitle(/./, { selector: "iframe" });
    expect(frames).toHaveLength(LEARNING_VIDEOS.length);
    for (const frame of frames) {
      expect(frame.getAttribute("src")).toMatch(/^https:\/\/www\.youtube-nocookie\.com\/embed\//);
      expect(frame).toHaveAttribute("loading", "lazy");
    }
  });

  it("collapses and persists the choice", async () => {
    const { user } = await import("./support/user"); // if no such helper exists, use userEvent.setup()
    render(<VideoSection />);
    await user.click(screen.getByRole("button", { name: /learning science/i }));
    expect(screen.queryByTitle(LEARNING_VIDEOS[0].title)).not.toBeInTheDocument();
    expect(localStorage.getItem("smv2.dashboard.videos")).toBe("collapsed");
  });
});
```

Before writing this, check `__tests__/support/` for the house pattern for userEvent + localStorage mocks and copy it (smv2-testing-standards owns the details; localStorage/matchMedia stubs already exist for other tests).

- [ ] **Step 3: Run to fail**, then implement:

```ts
// lib/dashboard/videos.ts
/** Curated, deterministic list — IDs verified against YouTube oEmbed at authoring time (Task 5 Step 1). */
export interface LearningVideo {
  videoId: string;
  title: string;
  blurb: string;
}

export const LEARNING_VIDEOS: LearningVideo[] = [
  // Filled in Step 1 with verified entries, e.g.:
  // { videoId: "<verified-11-char-id>", title: "<exact video title>", blurb: "<one sentence>" },
];
```

```tsx
// components/dashboard/VideoSection.tsx
"use client";

import { useEffect, useState } from "react";

import { LEARNING_VIDEOS } from "@/lib/dashboard/videos";

const STORAGE_KEY = "smv2.dashboard.videos";

/**
 * Bottom-of-dashboard learning-science explainers (spec §4). Direct
 * iframes by explicit user decision; youtube-nocookie + loading=lazy keep
 * it private-ish and free until scrolled into view. Collapse state
 * persists so it stays out of the way once dismissed.
 */
export default function VideoSection() {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(localStorage.getItem(STORAGE_KEY) === "collapsed");
  }, []);

  function toggle() {
    setCollapsed((value) => {
      const next = !value;
      localStorage.setItem(STORAGE_KEY, next ? "collapsed" : "expanded");
      return next;
    });
  }

  if (LEARNING_VIDEOS.length === 0) return null;

  return (
    <section aria-labelledby="learning-science-heading" className="flex flex-col gap-3">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={!collapsed}
        className="flex items-center gap-2 self-start text-sm font-semibold"
      >
        <span aria-hidden="true">{collapsed ? "▸" : "▾"}</span>
        <span id="learning-science-heading">Learning science — why this app works this way</span>
      </button>
      {!collapsed && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {LEARNING_VIDEOS.map((video) => (
            <figure key={video.videoId} className="flex flex-col gap-2">
              <iframe
                src={`https://www.youtube-nocookie.com/embed/${video.videoId}`}
                title={video.title}
                loading="lazy"
                allowFullScreen
                className="aspect-video w-full rounded-lg border border-border"
              />
              <figcaption className="text-xs text-muted-foreground">{video.blurb}</figcaption>
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Run tests + typecheck** → PASS.
- [ ] **Step 5: Commit** — `feat(smv2): learning-science video section (verified ids, nocookie embeds)`

---

### Task 6: SiteHeader — ThemeToggle + token border

**Files:**
- Modify: `components/SiteHeader.tsx`
- Test: existing header/dashboard tests in `__tests__/` (run suite; update whichever asserts header contents)

- [ ] **Step 1: Replace SiteHeader.tsx body** (ThemeToggle is a client component; fine inside a server component):

```tsx
import Link from "next/link";

import DueBadge from "@/components/DueBadge";
import ThemeToggle from "@/components/ThemeToggle";

export default function SiteHeader() {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-border px-6 py-4">
      <h1 className="text-lg font-semibold">
        <Link href="/">SourceMind</Link>
      </h1>
      <div className="flex items-center gap-3">
        <DueBadge />
        <ThemeToggle />
      </div>
    </header>
  );
}
```

Keep the existing doc comment above the component.

- [ ] **Step 2:** `npm test -- --run` → fix any header-asserting test expectations (ThemeToggle now present app-wide). `npm run typecheck` → PASS.
- [ ] **Step 3: Commit** — `feat(smv2): theme toggle in global header`

---

### Task 7: Landing page rework

**Files:**
- Create: `components/dashboard/StatsRow.tsx`, `components/dashboard/QuizzesToTakePanel.tsx`
- Modify: `app/page.tsx`, `components/dashboard/ContinueCard.tsx`, `components/dashboard/ReviewCard.tsx`, `components/dashboard/CourseCard.tsx`, `components/dashboard/StudyNextList.tsx`
- Test: existing dashboard test file(s) in `__tests__/` + new `__tests__/quizzes-panel.test.tsx`

**Interfaces:**
- Consumes: Tasks 2–5 components/functions exactly as typed there; `getDueCountForCourse`, `listChapters`, `listSections` from the generated client (confirm exact exported names via `grep -n "listChapters\|getDueCount" lib/api/client.ts` first).
- Produces: `StatsRow({cardsDue, quizzesToTake, progressPercent, progressCourseTitle, backlogWarning})`; `QuizzesToTakePanel({courses})` (fetches internally, reports its count via `onCount?: (n: number) => void`).

- [ ] **Step 1: StatsRow**

```tsx
// components/dashboard/StatsRow.tsx
import Badge from "@/components/ui/Badge";
import StatTile from "@/components/ui/StatTile";

export interface StatsRowProps {
  cardsDue: number;
  quizzesToTake: number;
  progressPercent: number | null;
  progressCourseTitle: string | null;
  backlogWarning: boolean;
}

export default function StatsRow({
  cardsDue,
  quizzesToTake,
  progressPercent,
  progressCourseTitle,
  backlogWarning,
}: StatsRowProps) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <StatTile
        value={cardsDue}
        label={cardsDue === 1 ? "card due" : "cards due"}
        href="/review"
        hint={backlogWarning ? <Badge tone="warning">Backlog building up</Badge> : undefined}
      />
      <StatTile
        value={quizzesToTake}
        label={quizzesToTake === 1 ? "quiz to take" : "quizzes to take"}
        href="#quizzes"
      />
      <StatTile
        value={progressPercent != null ? `${progressPercent}%` : "—"}
        label={progressCourseTitle ? `through ${progressCourseTitle}` : "no course in progress"}
      />
    </div>
  );
}
```

- [ ] **Step 2: QuizzesToTakePanel** — fetch chapters for up to 6 ready courses ordered by `progress?.updated_at` desc (courses without progress last, original order), derive, render top 5:

```tsx
// components/dashboard/QuizzesToTakePanel.tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import Skeleton from "@/components/ui/Skeleton";
import { listChapters, type CourseOut } from "@/lib/api/client";
import { deriveQuizItems, type QuizItem } from "@/lib/dashboard/quizzes";

const COURSE_CAP = 6;
const ITEM_CAP = 5;

export interface QuizzesToTakePanelProps {
  courses: CourseOut[];
  onCount?: (count: number) => void;
}

export default function QuizzesToTakePanel({ courses, onCount }: QuizzesToTakePanelProps) {
  const [items, setItems] = useState<QuizItem[] | null>(null);

  useEffect(() => {
    let active = true;
    const targets = courses
      .filter((c) => c.status === "ready")
      .sort((a, b) => {
        const ta = a.progress?.updated_at ? Date.parse(a.progress.updated_at) : 0;
        const tb = b.progress?.updated_at ? Date.parse(b.progress.updated_at) : 0;
        return tb - ta;
      })
      .slice(0, COURSE_CAP);
    Promise.all(
      targets.map(async (course) => {
        const { data } = await listChapters(course.id);
        return { courseId: course.id, courseTitle: course.title, chapters: data ?? [] };
      }),
    ).then((entries) => {
      if (!active) return;
      const derived = deriveQuizItems(entries);
      setItems(derived);
      onCount?.(derived.length);
    });
    return () => {
      active = false;
    };
  }, [courses, onCount]);

  if (items === null) {
    return (
      <section id="quizzes" aria-label="Quizzes to take" className="flex flex-col gap-2">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-16 w-full" />
      </section>
    );
  }
  if (items.length === 0) return null; // quiet panel: nothing to nag about

  return (
    <section id="quizzes" aria-labelledby="quizzes-heading" className="flex flex-col gap-3">
      <h2 id="quizzes-heading" className="text-sm font-semibold">
        Quizzes to take
      </h2>
      <ul className="flex flex-col gap-2">
        {items.slice(0, ITEM_CAP).map((item) => (
          <li key={`${item.courseId}:${item.chapterLabel}`}>
            <Link href={`/course/${item.courseId}/chapter/${encodeURIComponent(item.chapterLabel)}/test`}>
              <Card interactive className="flex items-center justify-between gap-3 py-3">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{item.chapterTitle}</span>
                  <span className="block truncate text-xs text-muted-foreground">{item.courseTitle}</span>
                </span>
                {item.reason === "not_attempted" ? (
                  <Badge tone="accent">Not attempted</Badge>
                ) : (
                  <Badge tone="warning">Retake · best {item.bestScore}</Badge>
                )}
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

Confirm the chapter-test route shape first: `ls app/course/[courseId]/chapter` — adjust `href` to the real segment names.

- [ ] **Step 3: ContinueCard gains ProgressBar + Button.** In `components/dashboard/ContinueCard.tsx`, replace the returned JSX (keep all logic above it):

```tsx
  return (
    <Link
      href={`/course/${course.id}`}
      className="block rounded-lg border border-border bg-accent-soft/60 p-4 transition-colors hover:border-muted-foreground"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Continue reading
      </p>
      <h2 className="mt-1 text-lg font-semibold">{course.title}</h2>
      {chapter ? (
        <div className="mt-2 flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">
            {chapter.title} — {chapter.percent}% complete
          </p>
          <ProgressBar percent={chapter.percent} label={`Progress through ${course.title}`} />
        </div>
      ) : null}
    </Link>
  );
```

Add `import ProgressBar from "@/components/ui/ProgressBar";`.

- [ ] **Step 4: ReviewCard restyle** — same treatment: swap `bg-accent/5 … hover:bg-accent/10` for `bg-accent-soft/60 … hover:border-muted-foreground`; body unchanged.

- [ ] **Step 5: CourseCard migration.** In `components/dashboard/CourseCard.tsx`:
  - Delete local `StatusBadge` (lines 26–42). Import `Badge` and map: `tone="good"→"good"`, `"bad"→"serious"`, `"warning"→"warning"`, `"neutral"→"neutral"`. Ready badge: `<Badge tone="good">Ready</Badge>`; Draft: `<Badge tone="neutral">Draft</Badge>`; ingesting progress line keeps `role="status"` text but wrap card in `<Card className="flex flex-col gap-2">` replacing the outer `div` classes (line 154).
  - Failed-asset list items and failure message become `<Badge tone="serious">…</Badge>`; the expandable "N files failed extraction" trigger keeps its `<button aria-expanded>` wrapper with `<Badge tone="warning">` inside.
  - "Retry ingest" button → `<Button size="sm" disabled={retrying}>`; delete/confirm/cancel row → `<Button variant="danger" size="sm">` for Delete/Confirm, `<Button variant="ghost" size="sm">` for Cancel.
  - Read progress: add at the bottom of ready cards, reusing ContinueCard's pattern — if `course.progress?.section_id`, one `listSections` fetch in an effect (copy ContinueCard.tsx:29-55 logic verbatim, including the content-sections filter) and render `<ProgressBar percent={percent} label={`Progress through ${course.title}`} />`.
- [ ] **Step 6: StudyNextList reason chips → Badge.** Read the file; replace the reason chip span (its `className` starts with text color per reason, around line 100) with `<Badge tone={...}>` mapping: `low_test_score→warning`, `due_cards→accent`, `unread→neutral`, `stale→neutral`. Keep link + copy identical.

- [ ] **Step 7: page.tsx rework.** Changes only — all handlers/effects/state stay:
  - Widen: `max-w-3xl` → `max-w-5xl` (line 144).
  - Add state: `const [quizCount, setQuizCount] = useState(0);` and derived `progressPercent`/title: lift from ContinueCard? No — simplest source: reuse `continueCourse` and let StatsRow's percent come from a small `listSections` effect identical to ContinueCard's (extract that effect into `lib/dashboard/continue.ts` as `export function useContinueChapter(course: CourseOut | null): ChapterInfo | null` — move the interface + effect there, and refactor ContinueCard to consume the same hook so the logic exists once).
  - Header heading: `text-lg` → `text-2xl font-semibold tracking-tight`; Upload button → `<Button variant="primary">Upload PDF</Button>`.
  - Body order (inside the non-empty branch): `<StatsRow cardsDue={reviewSummary?.due_total ?? 0} quizzesToTake={quizCount} progressPercent={continueChapter?.percent ?? null} progressCourseTitle={continueCourse?.title ?? null} backlogWarning={Boolean(reviewSummary?.backlog_warning)} />`, then hero grid `grid gap-4 md:grid-cols-3` with `<div className="md:col-span-2"><ContinueCard …/></div>` + ReviewCard, then `<StudyNextList …/>`, then `<QuizzesToTakePanel courses={courses} onCount={setQuizCount} />`, then courses grid (now `sm:grid-cols-2 lg:grid-cols-3`), then `<VideoSection />`.
  - `showReviewCard` logic unchanged. Loading: while `!loaded`, render a skeleton column (`<Skeleton className="h-24" />` ×3) instead of nothing.
  - Empty state: swap the dashed div (lines 209–213) for `<EmptyState icon="📚" title="Drop a PDF anywhere to start" body="Or use the Upload PDF button above." />` keeping the outer conditional.
  - `onCount` is a `useState` setter (stable identity) — safe as the panel's effect dep; do NOT wrap another inline lambda around it (see smv2-frontend-feature "Maximum update depth" trap).

- [ ] **Step 8: Tests.** New `__tests__/quizzes-panel.test.tsx`: mock `listChapters` (house client-mock pattern — check an existing dashboard test for how `@/lib/api/client` is mocked and copy it) returning one never-attempted + one low-score chapter → expect two cards, badges "Not attempted"/"Retake"; empty stats → panel renders nothing. Update existing dashboard tests for new headings/roles. Run `npm test -- --run` + `npm run typecheck` → PASS.
- [ ] **Step 9: Commit** — `feat(smv2): rich dashboard landing (stats, quizzes panel, videos)`

---

### Task 8: Review page restyle

**Files:**
- Modify: `app/review/page.tsx`
- Test: existing review test file in `__tests__/`

- [ ] **Step 1: Grade buttons (lines 584–595) — color-coded, not color-alone (glyph + label + number stay):**

```tsx
          <div className="flex justify-center gap-3">
            {(
              [
                { value: 1, classes: "border-status-serious/40 bg-status-serious-soft text-status-serious" },
                { value: 2, classes: "border-status-warning/40 bg-status-warning-soft text-status-warning" },
                { value: 3, classes: "border-status-good/40 bg-status-good-soft text-status-good" },
                { value: 4, classes: "border-accent/40 bg-accent-soft text-accent" },
              ] as const
            ).map(({ value, classes }) => (
              <button
                key={value}
                type="button"
                onClick={() => grade(value)}
                className={`rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:opacity-80 ${classes}`}
              >
                {GRADE_LABELS[value]} ({value})
              </button>
            ))}
          </div>
```

- [ ] **Step 2: States.**
  - Card face (line 566): `rounded-lg border border-border p-6` → `rounded-lg border border-border bg-surface-raised p-6`.
  - Reveal button (line 579): → `<Button variant="primary" size="md" onClick={reveal} className="self-center px-6">Reveal (space)</Button>`.
  - Session-size buttons (line 494): → `<Button variant="primary" onClick={() => startSession(option.value)}>Review {option.label}</Button>`.
  - Every `Loading review summary… / Loading review queue… / Loading cards…` `<p role="status">` → keep the `role="status"` element for a11y but render `<Skeleton className="mx-auto mt-8 h-40 w-full max-w-2xl" />` beneath a visually-hidden text (`<span className="sr-only">Loading…</span>`).
  - The three identical "No cards due" blocks (lines 412–418, 468–474, 519–525) → `<EmptyState icon="✨" title="All caught up" body="Generate flashcards from a chapter, or keep reading." />` (wrapped in the same centering container).
  - Hub course rows (line 438) and "Session complete" block: wrap rows in `Card interactive`; summary counts get `<Badge>` tones matching grade colors.
- [ ] **Step 3:** `npm test -- --run` → update assertions on removed literal texts (e.g. "No cards due" → "All caught up"). `npm run typecheck` → PASS.
- [ ] **Step 4: Commit** — `style(smv2): review surface on ui primitives, coded grade buttons`

---

### Task 9: Quiz surfaces

**Files:**
- Modify: `components/test/TestAttemptClient.tsx`, `components/reader/ChapterTestClient.tsx` (confirm paths: `grep -rn "ChapterTestClient" components/ | head`)
- Test: existing test files for these surfaces in `__tests__/`

- [ ] **Step 1: Read both files fully before editing.** Logic (submission, grading display, `notifyReviewSettled`) is untouched — this is a reskin.
- [ ] **Step 2: TestAttemptClient.**
  - Above the current question, add: `<p role="status" className="text-sm text-muted-foreground">Question {index + 1} of {questions.length}</p>` followed by `<ProgressBar percent={((index + 1) / questions.length) * 100} label="Quiz progress" />` (adapt variable names to the file's real ones).
  - Each answer option label row: keep the `<input type="radio">` + `<label>` association exactly; style the label row `flex items-start gap-3 rounded-lg border border-border bg-surface-raised p-3 transition-colors hover:border-muted-foreground has-checked:border-accent has-checked:bg-accent-soft/40` (Tailwind v4 `has-checked:` = `&:has(:checked)`; verify it compiles in `npm run build`, else use a `checked`-derived conditional class from the existing state).
  - Results: score hero `<StatTile value={`${score}%`} label={`${correct} of ${total} correct`} />` (map to the component's real score fields); each per-question result block → `<Card>` with existing ✓/✗ + explanation inside; ✓/✗ become `<Badge tone="good">Correct</Badge>` / `<Badge tone="serious">Incorrect</Badge>`.
  - Primary actions (Submit/Next/Start review/Retake) → `Button variant="primary"`; secondary → default `Button`.
- [ ] **Step 3: ChapterTestClient.** Mastery bar → `<ProgressBar percent={…} label="Chapter mastery" />`; history list rows → `<Card className="flex items-center justify-between">` with date + `<Badge tone={score >= QUIZ_RETAKE_THRESHOLD ? "good" : "warning"}>{score}</Badge>` (import threshold from `@/lib/dashboard/quizzes` — single source); generate/retake buttons → `Button`.
- [ ] **Step 4:** `npm test -- --run` (update surface tests) + `npm run typecheck` → PASS.
- [ ] **Step 5: Commit** — `style(smv2): quiz surfaces on ui primitives`

---

### Task 10: Upload flow restyle + step indicator

**Files:**
- Modify: `components/upload/UploadFlow.tsx` (+ `components/upload/OutlineConfirmation.tsx` buttons only)
- Test: existing upload tests in `__tests__/`

- [ ] **Step 1: Read UploadFlow.tsx.** Identify its state-machine states (title entry → creating → uploading → ingest progress).
- [ ] **Step 2: Add step indicator** at the top of the modal (map the machine's states to steps 1–3):

```tsx
const STEPS = ["Name", "Upload", "Ingest"] as const;
// currentStep: 0|1|2 derived from the existing state value

<ol aria-label="Upload progress" className="flex items-center gap-2 text-xs">
  {STEPS.map((step, i) => (
    <li key={step} className="flex items-center gap-2">
      <span
        aria-current={i === currentStep ? "step" : undefined}
        className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold ${
          i < currentStep
            ? "bg-status-good-soft text-status-good"
            : i === currentStep
              ? "bg-accent text-white"
              : "bg-muted-foreground/15 text-muted-foreground"
        }`}
      >
        {i < currentStep ? "✓" : i + 1}
      </span>
      <span className={i === currentStep ? "font-medium" : "text-muted-foreground"}>{step}</span>
      {i < STEPS.length - 1 && <span aria-hidden="true" className="text-muted-foreground">—</span>}
    </li>
  ))}
</ol>
```

- [ ] **Step 3: Migrate buttons/containers** per the Global-Constraints migration table in both files. Modal container → `Card className="…"` keeping existing dialog/focus attributes (`useDialogFocus` wiring untouched).
- [ ] **Step 4:** `npm test -- --run` + `npm run typecheck` → PASS.
- [ ] **Step 5: Commit** — `style(smv2): upload flow on ui primitives + step indicator`

---

### Task 11: Reader TopBar overflow menu

**Files:**
- Modify: `components/reader/TopBar.tsx`
- Test: existing reader/topbar tests in `__tests__/`

- [ ] **Step 1: Restructure TopBar.tsx.** Keep every prop and control; change only layout. The three mid-bar controls (Edit outline, GenerateAllLessons, QuizzesPanel) render inline at `lg+` and inside a popover below `lg`:

```tsx
"use client"; // add only if not already a client component via its parent — check first

import { useRef, useState } from "react";
// existing imports stay

// inside TopBar(), before return:
const [menuOpen, setMenuOpen] = useState(false);
const menuRef = useRef<HTMLDivElement>(null);
useDismissOnOutsideOrEscape(menuRef, menuOpen, () => setMenuOpen(false));
// ^ import from "@/lib/hooks/useDismissOnOutsideOrEscape"; check the hook's real
//   signature with: grep -n "export function useDismissOnOutsideOrEscape" -A 5 lib/hooks/*.ts
//   and match it exactly.

// in JSX — wrap the three mid controls:
<div className="hidden items-center gap-2 lg:flex">
  <button type="button" onClick={onOpenOutlineEditor} className="rounded-md border border-border px-2 py-1 text-sm">
    Edit outline
  </button>
  <GenerateAllLessons courseId={courseId} onSectionSettled={onLessonSectionSettled} />
  <QuizzesPanel courseId={courseId} />
</div>
<div ref={menuRef} className="relative lg:hidden">
  <button
    type="button"
    onClick={() => setMenuOpen((v) => !v)}
    aria-expanded={menuOpen}
    aria-haspopup="true"
    aria-label="More actions"
    className="rounded-md border border-border px-2 py-1 text-sm"
  >
    ⋯
  </button>
  {menuOpen && (
    <div className="absolute right-0 top-full z-30 mt-1 flex w-56 flex-col gap-2 rounded-lg border border-border bg-background p-3 shadow-lg">
      <button type="button" onClick={() => { setMenuOpen(false); onOpenOutlineEditor(); }} className="rounded-md border border-border px-2 py-1 text-left text-sm">
        Edit outline
      </button>
      <GenerateAllLessons courseId={courseId} onSectionSettled={onLessonSectionSettled} />
      <QuizzesPanel courseId={courseId} />
    </div>
  )}
</div>
```

Chat/view-toggle/typography/theme controls stay inline at all widths. GenerateAllLessons and QuizzesPanel are stateful — verify (by reading them) they render self-contained triggers safe to mount in both slots; they mount in only ONE slot at a time (`hidden lg:flex` vs `lg:hidden`), but BOTH are in the DOM — if either runs SSE effects on mount, render them once and move via CSS is not enough; instead render inline-or-menu conditionally from a `useMediaQuery`-style check. Decide after reading; note the choice in the commit body.

- [ ] **Step 2:** `npm test -- --run` + `npm run typecheck` → PASS. Manual: `../dev.sh` from `smv2/`, shrink window below 1024px, menu appears, Escape/outside-click closes, focus returns to trigger.
- [ ] **Step 3: Commit** — `feat(smv2): responsive reader topbar with overflow menu`

---

### Task 12: Final gate + visual pass

- [ ] **Step 1:** From `smv2/`: `./build.sh` → every stage PASS. Fix anything it flags.
- [ ] **Step 2: Render and look (dataviz step 7).** `./dev.sh`; visit `/` (populated + empty DB states if available), `/review`, a course reader, a quiz. Check both themes via the new header toggle: no unreadable text on soft fills, no layout overflow at 800px width, videos section collapses/persists.
- [ ] **Step 3: Spec sweep.** Re-read the spec's section list; confirm each shipped. Confirm no stray `bg-black … dark:bg-white` buttons remain: `grep -rn "dark:bg-white dark:text-black" app components` → expect zero hits.
- [ ] **Step 4: Commit any fixups** — `style(smv2): ui overhaul fixups from final visual pass`

---

## Self-review notes (already applied)

- Spec coverage: §1→Tasks 1–3, §2→Tasks 6–7, §3→Task 4, §4→Task 5, §5→Task 8, §6→Task 9, §7→Tasks 10–11, §8 preserved by constraints, §9 embedded per task + Task 12.
- Threshold single-sourced: `QUIZ_RETAKE_THRESHOLD` defined once (Task 4), imported in Task 9.
- Read-before-edit steps included for every file not fully quoted in this plan (Tasks 9, 10, 11 Step 1s); field-name verification steps for `ChapterOut` and client function names (Tasks 4, 7).
