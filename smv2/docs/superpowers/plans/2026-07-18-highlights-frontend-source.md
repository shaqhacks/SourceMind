# Highlights Frontend — Source View (Plan 2 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the reader's **source (markdown) view**, a student can select text, highlight it in a color, attach a note, and send the selected passage to the course AI chat with one click — all backed by the Plan-1 API.

**Architecture:** Anchors are **text-quote selectors captured from and resolved against the rendered markdown DOM** (not `body_md`). A pure matcher (`lib/annotations/anchors.ts`) turns a `Selection` into `{exact, prefix, suffix, occurrence}` and back into a DOM `Range`. Stored highlights are painted with the browser-native **CSS Custom Highlight API** (`CSS.highlights` + `::highlight()`), one registry entry per color — no DOM mutation, no dependency. "Explain" threads the selected passage into the existing `CourseChatDrawer` via the Plan-1 `ChatIn.selection` field.

**Tech Stack:** Next.js 16.2 (App Router) + React 19 + TypeScript, Tailwind v4 (utility classes + `globals.css` custom-property tokens), `openapi-fetch` client (`lib/api/client.ts`), Vitest + Testing Library + `@testing-library/user-event`, jsdom.

## Global Constraints

- Everything lives under `smv2/frontend/` — never touch repo-root `frontend/` (that's the v1 app).
- Frontend cwd is `smv2/frontend`: tests `npm test -- --run`, typecheck `npm run typecheck`, lint `npm run lint`, build `npm run build`. The only CI-trusted gate is `./build.sh` from `smv2/`.
- **Anchor space is the rendered DOM text, never `body_md`.** `exact`/`prefix`/`suffix` are captured from `window.getSelection()` over the article DOM and resolved against that same DOM. `body_md` (markdown source, with `**`/`#`/etc.) is a *different* text space — the backend's `body_md.find(exact)` for chat grounding is best-effort and degrades gracefully; the frontend never anchors into `body_md`.
- All API calls go through `lib/api/client.ts` (the one `openapi-fetch` boundary). Never call `fetch` directly. Types come from `components["schemas"][...]`, never hand-written.
- `lib/api/schema.d.ts` and `smv2/openapi.json` are generated; Plan 1 already regenerated them with the highlight ops and `ChatIn.selection`. Do **not** edit or regenerate them in this plan.
- Highlight colors are exactly `yellow | green | blue | pink`. Color values come from `globals.css` custom-property tokens (`--highlight-*`), never hardcoded hex in components.
- Feature-detect `CSS.highlights`: if absent, **all** annotation UI is hidden and nothing throws (graceful no-op) — the reader must work unchanged in a browser without the API.
- Highlight rendering is gated to `mode === "source"` only. Lesson and pages views show no source-view highlights (pages view is Plan 3).
- Popovers/menus reuse `useDismissOnOutsideOrEscape(open, onClose, ref)` + `useDialogFocus(open, {trap:false})`; a popover that must shadow reader shortcuts opens a scope via `useKeyboardShortcuts({}, open)`. Reader keys `j k s c o ?` are taken — don't rebind them.
- Errors surface via the existing `ErrorBanner`/`describeError` convention; distinguish 404 via `status`.
- Commit messages: lowercase conventional (`feat: ...`) ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Anchor matcher (`lib/annotations/anchors.ts`)

The pure heart of the feature. No React, no DOM-framework — just `Selection`/`Range`/`Node` DOM primitives. Heavily unit-tested.

**Files:**
- Create: `smv2/frontend/lib/annotations/anchors.ts`
- Test: `smv2/frontend/__tests__/annotations/anchors.test.ts`

**Interfaces:**
- Produces:
  - `type QuoteSelector = { exact: string; prefix: string; suffix: string; occurrence: number }`
  - `selectorFromRange(container: HTMLElement, range: Range): QuoteSelector | null` — null if the range is empty/collapsed or outside `container`.
  - `rangeForSelector(container: HTMLElement, selector: QuoteSelector): Range | null` — null if not locatable.
  - `CONTEXT_LEN = 32` (chars of prefix/suffix captured; ≤ 64 per the API cap).
  Tasks 5–7 consume both functions; the selector shape matches `HighlightIn`/`HighlightOut` fields exactly.

**Design notes (read before implementing):**
- Work over the container's **text content** via a `TreeWalker(container, NodeFilter.SHOW_TEXT)`. Build one concatenated string plus an index of `(textNode, startOffset)` so a character position in the concatenation maps back to a `(node, offset)` for `Range.setStart/setEnd`.
- `occurrence` = how many times `exact` (with the same `prefix`/`suffix` context available) appears at-or-before the selected start, so repeated identical phrases are disambiguated. Concretely: count matches of `exact` in the concatenated text; the selected one is the k-th (0-based).
- Matching is done on the **raw concatenated DOM text** (which is already the rendered, syntax-free text). Do **not** collapse whitespace — the DOM text and the captured `exact` come from the same source, so exact substring matching is correct and simplest. (Whitespace normalization is unnecessary here precisely because both sides are the same DOM; adding it would risk offset drift.)

- [ ] **Step 1: Write the failing tests**

Create `smv2/frontend/__tests__/annotations/anchors.test.ts`:

```ts
import { describe, expect, it, beforeEach } from "vitest";
import { selectorFromRange, rangeForSelector } from "@/lib/annotations/anchors";

function container(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

// Build a Range spanning the first occurrence of `needle` within a single text node.
function rangeOf(el: HTMLElement, needle: string, nth = 0): Range {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let seen = 0;
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const text = node.textContent ?? "";
    let from = 0;
    for (;;) {
      const i = text.indexOf(needle, from);
      if (i === -1) break;
      if (seen === nth) {
        const r = document.createRange();
        r.setStart(node, i);
        r.setEnd(node, i + needle.length);
        return r;
      }
      seen++;
      from = i + needle.length;
    }
  }
  throw new Error(`needle not found: ${needle}`);
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("selectorFromRange", () => {
  it("captures exact plus surrounding context", () => {
    const el = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const sel = selectorFromRange(el, rangeOf(el, "powerhouse"));
    expect(sel).not.toBeNull();
    expect(sel!.exact).toBe("powerhouse");
    expect(sel!.prefix.endsWith("the ")).toBe(true);
    expect(sel!.suffix.startsWith(" of")).toBe(true);
    expect(sel!.occurrence).toBe(0);
  });

  it("returns null for a collapsed range", () => {
    const el = container("<p>hello</p>");
    const r = document.createRange();
    r.setStart(el.firstChild!.firstChild!, 2);
    r.collapse(true);
    expect(selectorFromRange(el, r)).toBeNull();
  });

  it("numbers a repeated phrase by occurrence", () => {
    const el = container("<p>ion channel ... ion channel ... ion channel</p>");
    expect(selectorFromRange(el, rangeOf(el, "ion channel", 0))!.occurrence).toBe(0);
    expect(selectorFromRange(el, rangeOf(el, "ion channel", 2))!.occurrence).toBe(2);
  });

  it("spans across element boundaries", () => {
    const el = container("<p>alpha <strong>beta</strong> gamma</p>");
    // Select "beta gamma" across the <strong> boundary.
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const beta = walker.nextNode() && walker.currentNode; // "alpha "
    // simpler: build range from "beta" start to end of " gamma"
    const strongText = el.querySelector("strong")!.firstChild!;
    const tailText = el.childNodes[2]; // " gamma"
    const r = document.createRange();
    r.setStart(strongText, 0);
    r.setEnd(tailText, tailText.textContent!.length);
    const sel = selectorFromRange(el, r);
    expect(sel!.exact).toBe("beta gamma");
  });
});

describe("rangeForSelector round-trip", () => {
  it("relocates the same text", () => {
    const el = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const sel = selectorFromRange(el, rangeOf(el, "powerhouse"))!;
    const r = rangeForSelector(el, sel)!;
    expect(r).not.toBeNull();
    expect(r.toString()).toBe("powerhouse");
  });

  it("relocates the correct occurrence of a repeat", () => {
    const el = container("<p>ion channel A ion channel B ion channel C</p>");
    const sel = selectorFromRange(el, rangeOf(el, "ion channel", 2))!;
    const r = rangeForSelector(el, sel)!;
    // The 3rd occurrence is immediately followed by " C".
    const after = r.endContainer.textContent!.slice(r.endOffset, r.endOffset + 2);
    expect(after).toBe(" C");
  });

  it("returns null when the text is absent", () => {
    const el = container("<p>nothing here</p>");
    expect(rangeForSelector(el, { exact: "absent", prefix: "", suffix: "", occurrence: 0 })).toBeNull();
  });

  it("returns null when occurrence is out of range", () => {
    const el = container("<p>once</p>");
    expect(rangeForSelector(el, { exact: "once", prefix: "", suffix: "", occurrence: 5 })).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (cwd `smv2/frontend`): `npm test -- --run __tests__/annotations/anchors.test.ts`
Expected: FAIL — module not found / functions undefined.

- [ ] **Step 3: Implement `anchors.ts`**

Create `smv2/frontend/lib/annotations/anchors.ts`:

```ts
/**
 * Text-quote anchoring over a rendered DOM subtree.
 *
 * Anchors live in the RENDERED text space (what the user selects), never in
 * body_md. selectorFromRange captures a selection as {exact, prefix, suffix,
 * occurrence}; rangeForSelector relocates it. occurrence disambiguates a
 * phrase that repeats. Matching is plain substring search over the container's
 * concatenated text nodes — both capture and resolve read the same DOM, so no
 * whitespace normalization is needed (and adding it would drift offsets).
 */

export type QuoteSelector = {
  exact: string;
  prefix: string;
  suffix: string;
  occurrence: number;
};

export const CONTEXT_LEN = 32;

type FlatText = {
  text: string;
  // For each character index i in `text`, nodeAt[i]/offsetAt[i] give the DOM
  // position. Length === text.length + 1 (the extra entry marks the end).
  nodeAt: Text[];
  offsetAt: number[];
};

function flatten(container: HTMLElement): FlatText {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let text = "";
  const nodeAt: Text[] = [];
  const offsetAt: number[] = [];
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const t = node as Text;
    const s = t.data;
    for (let i = 0; i < s.length; i++) {
      nodeAt.push(t);
      offsetAt.push(i);
    }
    text += s;
  }
  return { text, nodeAt, offsetAt };
}

function rangeFromFlat(flat: FlatText, start: number, end: number): Range | null {
  if (start < 0 || end > flat.text.length || start >= end) return null;
  const range = document.createRange();
  range.setStart(flat.nodeAt[start], flat.offsetAt[start]);
  // end is exclusive; anchor to the last included char + 1.
  range.setEnd(flat.nodeAt[end - 1], flat.offsetAt[end - 1] + 1);
  return range;
}

// Character offset in `flat.text` for a (node, offset) DOM position, or -1.
function flatIndexOf(flat: FlatText, node: Node, offset: number): number {
  for (let i = 0; i < flat.nodeAt.length; i++) {
    if (flat.nodeAt[i] === node && flat.offsetAt[i] === offset) return i;
  }
  // A range end can point one past the last char of a text node.
  for (let i = 0; i < flat.nodeAt.length; i++) {
    if (flat.nodeAt[i] === node && flat.offsetAt[i] + 1 === offset && (i + 1 === flat.nodeAt.length || flat.nodeAt[i + 1] !== node)) {
      return i + 1;
    }
  }
  return -1;
}

export function selectorFromRange(container: HTMLElement, range: Range): QuoteSelector | null {
  if (range.collapsed) return null;
  if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) return null;

  const flat = flatten(container);
  const start = flatIndexOf(flat, range.startContainer, range.startOffset);
  const end = flatIndexOf(flat, range.endContainer, range.endOffset);
  if (start === -1 || end === -1 || start >= end) return null;

  const exact = flat.text.slice(start, end);
  if (exact.length === 0) return null;
  const prefix = flat.text.slice(Math.max(0, start - CONTEXT_LEN), start);
  const suffix = flat.text.slice(end, end + CONTEXT_LEN);

  // occurrence = number of matches of `exact` that start strictly before this one.
  let occurrence = 0;
  let from = flat.text.indexOf(exact);
  while (from !== -1 && from < start) {
    occurrence++;
    from = flat.text.indexOf(exact, from + 1);
  }
  return { exact, prefix, suffix, occurrence };
}

export function rangeForSelector(container: HTMLElement, selector: QuoteSelector): Range | null {
  const { exact, occurrence } = selector;
  if (!exact) return null;
  const flat = flatten(container);

  let seen = 0;
  let from = flat.text.indexOf(exact);
  while (from !== -1) {
    if (seen === occurrence) return rangeFromFlat(flat, from, from + exact.length);
    seen++;
    from = flat.text.indexOf(exact, from + 1);
  }
  return null;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (cwd `smv2/frontend`): `npm test -- --run __tests__/annotations/anchors.test.ts`
Expected: PASS, all cases. Then `npm run typecheck` — Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/shaquillejohnson/code/SourceMind && git add smv2/frontend/lib/annotations/anchors.ts smv2/frontend/__tests__/annotations/anchors.test.ts && git commit -m "feat: add text-quote anchor matcher for highlights

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: API client functions + selection on sendChat

**Files:**
- Modify: `smv2/frontend/lib/api/client.ts` (type exports near line 20; new functions near the other course-scoped calls; `sendChat` at ~line 579)
- Test: none new (thin wrappers, verified by typecheck and by consumers in later tasks — matches the repo's existing convention of not unit-testing `client.ts` shims directly).

**Interfaces:**
- Produces (Tasks 4–9 consume):
  - `export type HighlightOut = components["schemas"]["HighlightOut"]`
  - `export type HighlightIn = components["schemas"]["HighlightIn"]`
  - `export type HighlightUpdateIn = components["schemas"]["HighlightUpdateIn"]`
  - `export type ChatSelectionIn = components["schemas"]["ChatSelectionIn"]`
  - `listHighlights(courseId: string)` → `ApiResult<HighlightOut[]>`
  - `createHighlight(courseId: string, body: HighlightIn)` → `ApiResult<HighlightOut>`
  - `updateHighlight(highlightId: string, body: HighlightUpdateIn)` → `ApiResult<HighlightOut>`
  - `deleteHighlight(highlightId: string)` → `ApiResult<undefined>`
  - `sendChat(courseId, message, selection?: ChatSelectionIn)` — extended, third param optional.

- [ ] **Step 1: Add the type exports**

In `smv2/frontend/lib/api/client.ts`, beside the existing `export type SectionOut = components["schemas"]["SectionOut"];` block, add the four type exports listed above.

- [ ] **Step 2: Add the four client functions**

Mirror the existing `getSection` (GET path param), `editOutline` (PATCH), and `deleteCard` (DELETE 204) shapes exactly:

```ts
export function listHighlights(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/highlights", {
      params: { path: { course_id: courseId } },
    }),
  );
}

export function createHighlight(courseId: string, body: HighlightIn) {
  return request(
    client.POST("/api/courses/{course_id}/highlights", {
      params: { path: { course_id: courseId } },
      body,
    }),
  );
}

export function updateHighlight(highlightId: string, body: HighlightUpdateIn) {
  return request(
    client.PATCH("/api/highlights/{highlight_id}", {
      params: { path: { highlight_id: highlightId } },
      body,
    }),
  );
}

export function deleteHighlight(highlightId: string) {
  return request(
    client.DELETE("/api/highlights/{highlight_id}", {
      params: { path: { highlight_id: highlightId } },
    }),
  );
}
```

- [ ] **Step 3: Extend `sendChat`**

Replace the existing `sendChat`:

```ts
export function sendChat(courseId: string, message: string, selection?: ChatSelectionIn) {
  return request(
    client.POST("/api/courses/{course_id}/chat", {
      params: { path: { course_id: courseId } },
      body: { message, selection: selection ?? null },
    }),
  );
}
```

The added third param is optional, so the existing single-selection-free call site in `CourseChatDrawer` still compiles unchanged.

- [ ] **Step 4: Verify**

Run (cwd `smv2/frontend`): `npm run typecheck` — Expected: clean. `npm test -- --run __tests__/course-chat-drawer.test.tsx` — Expected: the existing chat-drawer test still passes (sendChat's new optional param doesn't change its 2-arg calls).

- [ ] **Step 5: Commit**

```bash
cd /Users/shaquillejohnson/code/SourceMind && git add smv2/frontend/lib/api/client.ts && git commit -m "feat: add highlight client functions and chat selection param

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Color tokens + CSS Custom Highlight API test shim

**Files:**
- Modify: `smv2/frontend/app/globals.css` (`:root` light block, dark `@media`/`[data-theme]` blocks, `@theme inline`)
- Modify: `smv2/frontend/vitest.setup.ts` (add a guarded `CSS.highlights`/`Highlight` polyfill next to the `matchMedia`/`scrollTo` shims)
- Test: `smv2/frontend/__tests__/annotations/highlight-registry.test.ts` (new — proves the shim works, so later component tests can rely on it)

**Interfaces:**
- Produces: CSS custom properties `--highlight-{yellow,green,blue,pink}` and their painted `::highlight(hl-{color})` rules; a jsdom polyfill so `CSS.highlights` is a `Map` and `new Highlight(...)` exists in tests. Task 5's painter registers highlights under names `hl-yellow|hl-green|hl-blue|hl-pink`.

- [ ] **Step 1: Add tokens and `::highlight` rules to `globals.css`**

Follow the existing `--status-good`/`--status-good-soft` light/dark/`@theme` triple pattern. Add to the `:root` light block readable, low-saturation backgrounds (e.g. `--highlight-yellow: #fef3c7; --highlight-green: #dcfce7; --highlight-blue: #dbeafe; --highlight-pink: #fce7f3;`) and to the dark blocks darker translucent equivalents that keep the underlying serif text readable (e.g. `--highlight-yellow: rgba(250, 204, 21, 0.28);` etc. — the implementer picks dark values that pass a readability eyeball on `--foreground`). Then, once (not inside `@theme`), add the painted rules:

```css
::highlight(hl-yellow) { background-color: var(--highlight-yellow); }
::highlight(hl-green)  { background-color: var(--highlight-green); }
::highlight(hl-blue)   { background-color: var(--highlight-blue); }
::highlight(hl-pink)   { background-color: var(--highlight-pink); }
```

(No `@theme inline` entry is needed unless a Tailwind utility for these colors is wanted; the popover swatches in Task 6 can use inline `style={{ backgroundColor: "var(--highlight-yellow)" }}` to stay token-driven without new utilities.)

- [ ] **Step 2: Write the failing shim test**

Create `smv2/frontend/__tests__/annotations/highlight-registry.test.ts`:

```ts
import { describe, expect, it } from "vitest";

describe("CSS Custom Highlight API shim (jsdom)", () => {
  it("exposes CSS.highlights as a Map-like registry", () => {
    expect(typeof CSS).toBe("object");
    expect(CSS.highlights).toBeDefined();
    expect(typeof CSS.highlights.set).toBe("function");
    expect(typeof CSS.highlights.delete).toBe("function");
  });

  it("constructs a Highlight from ranges", () => {
    const r = document.createRange();
    const h = new Highlight(r);
    expect(h).toBeInstanceOf(Highlight);
    CSS.highlights.set("hl-yellow", h);
    expect(CSS.highlights.get("hl-yellow")).toBe(h);
    CSS.highlights.delete("hl-yellow");
    expect(CSS.highlights.has("hl-yellow")).toBe(false);
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run (cwd `smv2/frontend`): `npm test -- --run __tests__/annotations/highlight-registry.test.ts`
Expected: FAIL — `CSS`/`Highlight` undefined in jsdom.

- [ ] **Step 4: Add the guarded polyfill to `vitest.setup.ts`**

Following the file's existing `typeof … !== "function"` guard style used for `matchMedia`:

```ts
// CSS Custom Highlight API — absent in jsdom. Minimal registry so components
// that paint highlights don't throw under test. Behaviour (actual painting)
// is a browser concern; tests assert we CALL the registry correctly.
class HighlightPolyfill {
  private ranges: Set<Range>;
  constructor(...ranges: Range[]) {
    this.ranges = new Set(ranges);
  }
  add(r: Range) { this.ranges.add(r); }
  clear() { this.ranges.clear(); }
  get size() { return this.ranges.size; }
}
if (typeof (globalThis as any).Highlight !== "function") {
  (globalThis as any).Highlight = HighlightPolyfill;
}
if (typeof (globalThis as any).CSS !== "object" || (globalThis as any).CSS == null) {
  (globalThis as any).CSS = {};
}
if ((globalThis as any).CSS.highlights == null) {
  (globalThis as any).CSS.highlights = new Map();
}
```

- [ ] **Step 5: Run to verify pass**

Run (cwd `smv2/frontend`): `npm test -- --run __tests__/annotations/highlight-registry.test.ts` then `npm run typecheck`.
Expected: PASS; typecheck clean (add DOM lib types if TS complains about `Highlight`/`CSS.highlights` — the project targets a lib that includes them for browser code; if `Highlight` is unknown to TS in test files, declare it via `declare global` in the setup or a `types` shim, matching how the repo already handles ambient test globals).

- [ ] **Step 6: Commit**

```bash
cd /Users/shaquillejohnson/code/SourceMind && git add smv2/frontend/app/globals.css smv2/frontend/vitest.setup.ts smv2/frontend/__tests__/annotations/highlight-registry.test.ts && git commit -m "feat: add highlight color tokens and test-env highlight api shim

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `useHighlights` hook

Owns per-section highlight state + CRUD, with optimistic local updates and error surfacing.

**Files:**
- Create: `smv2/frontend/lib/hooks/useHighlights.ts`
- Test: `smv2/frontend/__tests__/annotations/use-highlights.test.tsx`

**Interfaces:**
- Consumes: `listHighlights`/`createHighlight`/`updateHighlight`/`deleteHighlight`, `HighlightOut`, `QuoteSelector` (Task 1), `describeError` (existing `lib/api/errors.ts`).
- Produces:
  ```ts
  type UseHighlights = {
    highlights: HighlightOut[];           // for the ACTIVE section only
    error: string | null;
    createFromSelector: (sel: QuoteSelector, color: HighlightColor, page: number | null) => Promise<HighlightOut | null>;
    updateOne: (id: string, patch: HighlightUpdateIn) => Promise<void>;
    deleteOne: (id: string) => Promise<void>;
    reload: () => void;
  };
  useHighlights(courseId: string, sectionId: string): UseHighlights
  ```
  `HighlightColor = "yellow" | "green" | "blue" | "pink"` (export it here; reused by Tasks 5–8).
  Tasks 5–8 consume this hook.

**Design notes:**
- Load on `[courseId, sectionId]`; store the full course list once and derive the active-section slice, OR fetch per-section — choose per-section fetch keyed on `sectionId` to keep it simple (the API is course-scoped, so filter client-side: fetch course list, filter `h.section_id === sectionId`). Keep a course-wide cache in a ref so the NotesPanel (Task 8) can reuse it via `reload`.
- Mutations update local state optimistically, then reconcile with the server response; on error set `error` (via `describeError`) and roll back.
- Follow the memoization rule from the repo: wrap every returned callback in `useCallback` so consumers' effects don't thrash (the CLAUDE.md Chat.js note about `loadHistory` memoization is the precedent).

- [ ] **Step 1: Write the failing tests** — cover: initial load filters to the section; `createFromSelector` POSTs and appends; `updateOne` PATCHes and reflects note/color; `deleteOne` removes; a failed create sets `error` and doesn't append. Mock `@/lib/api/client` with `vi.fn()` + the `ok`/`err` helpers from `__tests__/support/api-result`, and drive the hook with Testing Library's `renderHook` + `act`.

- [ ] **Step 2: Run to verify fail** (`npm test -- --run __tests__/annotations/use-highlights.test.tsx` → module missing).

- [ ] **Step 3: Implement `useHighlights.ts`** per the interface and design notes.

- [ ] **Step 4: Run to verify pass** + `npm run typecheck`.

- [ ] **Step 5: Commit** (`feat: add useHighlights hook`).

---

### Task 5: Highlight painter + Markdown wrapper (render stored highlights in source view)

**Files:**
- Modify: `smv2/frontend/components/Markdown.tsx` (add an optional `containerRef?: RefObject<HTMLDivElement | null>` + `className?` wrapper prop, OR leave `Markdown` untouched and wrap at the call site — pick wrapping at the call site to avoid changing the shared component's signature)
- Modify: `smv2/frontend/components/reader/ReadingColumn.tsx` (wrap the `mode === "source"` `<Markdown>` in a ref'd `<div>`; mount the painter)
- Create: `smv2/frontend/lib/annotations/useHighlightPainter.ts`
- Test: `smv2/frontend/__tests__/annotations/use-highlight-painter.test.tsx`

**Interfaces:**
- Consumes: `rangeForSelector` (Task 1), `HighlightOut`, `CSS.highlights`.
- Produces: `useHighlightPainter(containerRef, highlights, enabled): void` — repaints the `CSS.highlights` registry whenever `[highlights, enabled, containerRef.current]` change. Registers one `Highlight` per color under `hl-<color>`; clears all four names when `enabled` is false or the API is absent.

**Design notes:**
- Feature-detect once: `const supported = typeof CSS !== "undefined" && !!(CSS as any).highlights && typeof Highlight !== "undefined";`. If unsupported, the painter is a no-op and Tasks 6–8 hide their UI.
- Use `useLayoutEffect` so ranges are computed against the committed DOM. Recompute `rangeForSelector(container, sel)` for every highlight; group ranges by color; `CSS.highlights.set("hl-yellow", new Highlight(...ranges))` etc.; for a color with zero ranges, `CSS.highlights.delete("hl-<color>")`.
- **Cleanup:** on unmount or section change, delete all four registry names — the registry is global/document-scoped, so a stale range from a previous section would otherwise linger. This is the key footgun; the test must assert cleanup.
- Highlights that don't resolve (`rangeForSelector` returns null) are silently skipped (never throw) — they still appear in the NotesPanel (Task 8), just not painted.

- [ ] **Step 1: Write the failing tests** — render a component that mounts `useHighlightPainter` over a known DOM with two highlights of different colors; assert `CSS.highlights.get("hl-yellow")` and `get("hl-green")` are set with the right range counts; assert that toggling `enabled` to false clears them; assert unmount clears them; assert an unresolved selector doesn't throw and doesn't add a range.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement the painter, wrap the Markdown call in ReadingColumn** (a `<div ref={articleBodyRef}>` around only the `<Markdown>{body.body}</Markdown>` in the `mode === "source"` branch — NOT around the heading/CTA/cards), and mount `useHighlightPainter(articleBodyRef, highlights, mode === "source" && supported)`. Wire `useHighlights(courseId, activeSection.id)` in `ReadingColumn` (or in `CourseReader` and pass down — prefer `ReadingColumn` since that's where the DOM and the source-mode gate live).

- [ ] **Step 4: Run to verify pass** + `npm run typecheck` + `npm test -- --run __tests__/reading-column*.test.tsx` (existing ReadingColumn tests must still pass — the wrapper div and painter are additive and gated).

- [ ] **Step 5: Commit** (`feat: paint stored highlights in source view`).

---

### Task 6: SelectionPopover (create highlight / explain from a live selection)

**Files:**
- Create: `smv2/frontend/components/reader/SelectionPopover.tsx`
- Modify: `smv2/frontend/components/reader/ReadingColumn.tsx` (detect selection within the article-body wrapper; render the popover; call `createFromSelector` / raise "explain")
- Modify: `smv2/frontend/components/reader/CourseReader.tsx` (pass a new `onExplainSelection(sel: {sectionId, exact})` prop into `ReadingColumn` that opens the chat drawer and stashes the pending selection — see Task 9 for the drawer side)
- Test: `smv2/frontend/__tests__/annotations/selection-popover.test.tsx`

**Interfaces:**
- Consumes: `selectorFromRange` (Task 1), `useHighlights.createFromSelector` (Task 4), `useDismissOnOutsideOrEscape` + `useDialogFocus` (existing), `HighlightColor`.
- Produces: `SelectionPopover` props `{ anchorRect: DOMRect; onColor: (c: HighlightColor) => void; onExplain: () => void; onClose: () => void }`. Four color swatch buttons (token backgrounds), an "Explain" button.

**Design notes:**
- In `ReadingColumn`, listen for `selectionchange`/`mouseup` scoped to the article-body wrapper. On a non-collapsed selection whose anchor+focus are inside the wrapper, compute `selectorFromRange(wrapper, range)`; if non-null, position the popover at `range.getBoundingClientRect()`. Ignore selections in lesson/pages mode (gate on `mode === "source"`) and when unsupported.
- Choosing a color → `createFromSelector(sel, color, page)` where `page = section.page_start ?? null` (the section's 1-based first page, already on the `ReaderSection`) → clear the selection → the painter (Task 5) repaints from the new state.
- "Explain" → `onExplain()` bubbles `{sectionId: section.id, exact: sel.exact}` to `CourseReader` (Task 9 opens the drawer + attaches it) → clear selection + close popover.
- Reuse the dismiss/focus hooks; open a `useKeyboardShortcuts({}, true)` scope while the popover is open so `s`/`c`/etc. don't fire mid-annotation.

- [ ] **Step 1: Write the failing tests** — render `ReadingColumn` in source mode with a ready body; simulate a selection over known text (construct a Range, `window.getSelection().addRange`, dispatch `mouseup`); assert the popover appears; click the green swatch → assert `createHighlight` called with `{section_id, exact, color:"green", ...}`; click Explain → assert the `onExplainSelection` prop fired with `{sectionId, exact}`; press Escape → popover gone.

- [ ] **Step 2–5:** fail → implement → pass (`npm run typecheck`, existing ReadingColumn tests green) → commit (`feat: add selection popover for creating highlights`).

---

### Task 7: HighlightEditPopover (edit note / recolor / delete / explain an existing highlight)

**Files:**
- Create: `smv2/frontend/components/reader/HighlightEditPopover.tsx`
- Modify: `smv2/frontend/components/reader/ReadingColumn.tsx` (click within the article-body wrapper → hit-test painted highlights → open the edit popover for the smallest containing highlight)
- Test: `smv2/frontend/__tests__/annotations/highlight-edit-popover.test.tsx`

**Interfaces:**
- Consumes: `rangeForSelector` (hit-testing), `useHighlights.updateOne`/`deleteOne`, dismiss/focus hooks, `HighlightColor`, `Markdown` (to render `note_md` preview) or a plain `<textarea>` editor.
- Produces: `HighlightEditPopover` props `{ highlight: HighlightOut; anchorRect: DOMRect; onSave: (patch: HighlightUpdateIn) => void; onDelete: () => void; onExplain: () => void; onClose: () => void }`. A note `<textarea>` (markdown), four recolor swatches, Delete, Explain.

**Design notes:**
- Hit-test on `click` in the wrapper: for each highlight, resolve its range; find those whose `range` contains the click point (`range.getBoundingClientRect()` / `caretRangeFromPoint` where available; fall back to comparing the click's caret index against each selector's `[start,end)` computed via the same flatten used in anchors — expose a small helper or reuse `rangeForSelector` + `range.comparePoint`). Choose the **smallest** (shortest `exact`) containing highlight.
- The note editor is a `<textarea>` (so global shortcuts auto-ignore it per `isEditableTarget`); Save → `updateOne(id, {note_md})`; recolor → `updateOne(id, {color})`; Delete → `deleteOne(id)`; Explain → bubble `{sectionId: highlight.section_id, exact: highlight.exact}` up like Task 6.
- Reuse the same dismiss/focus/shortcut-scope trio.

- [ ] **Step 1: Write the failing tests** — paint a highlight, simulate a click on it, assert the edit popover opens with the existing `note_md`; type a note + Save → `updateHighlight(id, {note_md})`; click a swatch → `updateHighlight(id, {color})`; Delete → `deleteHighlight(id)` and highlight removed; Explain → prop fired.

- [ ] **Step 2–5:** fail → implement → pass → commit (`feat: add highlight edit popover`).

---

### Task 8: NotesPanel (course-wide highlights/notes list with navigation)

**Files:**
- Create: `smv2/frontend/components/reader/NotesPanel.tsx`
- Modify: `smv2/frontend/components/reader/CourseReader.tsx` (mount the panel; a toggle in `TopBar` or a reuse of the existing drawer pattern — read `TopBar.tsx` before choosing; simplest: a slide-over sibling of the chat drawer, opened by a new TopBar button)
- Test: `smv2/frontend/__tests__/annotations/notes-panel.test.tsx`

**Interfaces:**
- Consumes: `listHighlights` (course-wide), `HighlightOut`, `Markdown` (render `note_md`), the existing section-navigation path (`?section=<id>` / the reader's `goToSection`).
- Produces: `NotesPanel` props `{ courseId: string; open: boolean; onClose: () => void; onNavigate: (sectionId: string) => void }`. Lists every highlight (grouped by section, ordered by the API's section-order/created-at); each row shows the quoted `exact`, its color swatch, the note preview, and click-to-navigate. Highlights whose text no longer resolves in the current render still list here (they just aren't painted) — never hidden, never auto-deleted.

**Design notes:**
- Reuse the chat-drawer open/close idiom (`useChatOpenPref`-style localStorage pref is optional; a plain `useState` in `CourseReader` is fine since the panel isn't a per-course preference). Dismiss via the shared hook.
- Clicking a row calls `onNavigate(sectionId)` → the reader's existing section switch → the painter repaints that section's highlights.

- [ ] **Step 1: Write the failing tests** — mock `listHighlights` to return highlights across two sections; render the panel open; assert rows render with quotes + note previews grouped by section; click a row → `onNavigate(sectionId)` fired; assert a highlight with `note_md: null` still renders its quote.

- [ ] **Step 2–5:** fail → implement → pass → commit (`feat: add course notes panel`).

---

### Task 9: Explain-in-chat wiring (selection → drawer → composer chip → sendChat)

**Files:**
- Modify: `smv2/frontend/components/reader/CourseReader.tsx` (hold `pendingSelection` state; `onExplainSelection` opens the drawer + sets it; pass into `CourseChatDrawer`)
- Modify: `smv2/frontend/components/reader/CourseChatDrawer.tsx` (accept `pendingSelection` + `onConsumeSelection`; include it in the next `sendChat`; show a dismissible chip in the composer)
- Modify: `smv2/frontend/components/Chat.tsx` (extend `sendFn` signature to carry an optional selection; render a composer chip slot)
- Test: `smv2/frontend/__tests__/annotations/explain-in-chat.test.tsx`, and update `__tests__/course-chat-drawer.test.tsx`

**Interfaces:**
- Consumes: `sendChat(courseId, message, selection?)` (Task 2), `ChatSelectionIn`.
- Produces: the end-to-end path. `Chat`'s `sendFn` becomes `(message: string, selection?: {section_id: string; exact: string}) => Promise<ChatSendResult>`; `CourseChatDrawer` closes over `pendingSelection` and passes it to `sendChat`, then calls `onConsumeSelection()` so it attaches to exactly one turn.

**Design notes:**
- When "Explain" fires (Task 6/7), `CourseReader` sets `pendingSelection = {section_id, exact}` and opens the drawer (`setChatOpen(true)`). The drawer shows a chip ("Asking about: '…first 60 chars…'") above the composer with an ✕ to clear it. On send, `sendChat(courseId, message, pendingSelection)`; on success or manual clear, `onConsumeSelection()`.
- The stored user turn already gets the blockquote server-side (Plan 1), so the transcript shows the quote after send with no extra client work.
- Keep the no-selection path identical: a normal chat message sends `selection = undefined`.

- [ ] **Step 1: Write the failing tests** — render `CourseChatDrawer` with a `pendingSelection`; assert the chip shows; type a message + send → `sendChat` called with the selection object; assert `onConsumeSelection` fired; a second send has no selection. Separately, an integration-style test: fire Explain from a painted highlight → drawer opens with the chip.

- [ ] **Step 2–5:** fail → implement → pass (existing chat-drawer test updated for the new `sendFn` arity) → commit (`feat: explain a selected passage in course chat`).

---

### Task 10: Full gate

**Files:** none (verification; fixes land on whichever file broke).

- [ ] **Step 1:** (cwd `smv2/frontend`) `npm run lint` — Expected: 0 issues (new components included).
- [ ] **Step 2:** (cwd `smv2/frontend`) `npm test -- --run` — Expected: all suites pass, output pristine.
- [ ] **Step 3:** (cwd `smv2/`) `./build.sh` — Expected: every stage green (backend unchanged, frontend typecheck + tests + prod build). Backend OpenAPI export must produce NO diff (this plan doesn't touch backend). If the gate flags an artifact diff, something regenerated a generated file it shouldn't have — revert that.
- [ ] **Step 4:** Report gate output verbatim; if any stage failed, fix forward (smallest change), re-run `./build.sh`, note failure + fix.

---

## Verification beyond the gate (manual, recommended)

The gate proves it compiles and tests pass, but the CSS Custom Highlight API does not paint in jsdom. Before calling the feature done, drive it once in a real browser (`smv2/dev.sh`, open a course, source view): select text → pick a color → confirm the highlight paints and survives a section switch and return; add a note, reopen it; click Explain → confirm the chat drawer opens with the chip and the reply references the passage; confirm a browser with the API disabled shows the reader normally with no annotation UI and no console errors.

## Out of scope (this plan)

- PDF pages-view highlighting (Plan 3) — the anchor format and painter are reused there over the pdf.js text layer.
- Highlight styles beyond background color (underline/squiggly).
- Notes in the course-export zip.
- Remap-on-reingest survival (highlights are wiped on re-ingest per Plan 1 / ADR-024; the re-ingest UI warning is a small follow-up, note it if the upload flow is touched).

## Deviations from the spec (deliberate)

1. The spec named `useHighlights(courseId, sectionId)` and separate popover/panel components; this plan adds `useHighlightPainter` as a distinct hook so the render/paint concern is testable in isolation from CRUD state — a decomposition improvement, not a scope change.
2. Anchor capture/resolve is explicitly DOM-text-based (clarified in Global Constraints); the spec's `anchors.ts` signature is preserved.
