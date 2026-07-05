# SourceMind v2 — Build Brief

A greenfield rebuild brief distilled from v1's ADRs, bug history, and debt list.
The rules below are invariants learned by bleeding — a builder (human or agent)
executing this brief must ask before deviating from any law, and record approved
deviations as ADRs. See the appendix for the v1 pitfall each rule prevents.

## Mission

Local-first course workbook generator. User uploads PDFs → instant deterministic
outline and readable source-text chapters (zero LLM calls) → opt-in, lazily
generated lessons/study material → mdBook-style reader with spaced repetition
and RAG chat. FastAPI + SQLite backend, Next.js frontend. Single-user, runs on
a laptop. Optimize for cost, reproducibility, and restart-safety over cleverness.

## Prime directive: deterministic before generative

Every operation must first be attempted with code. An LLM call is a last
resort, and when used it is (a) scoped to the smallest possible input (one
chapter, never the whole book), (b) lazy — triggered by first user need, never
by ingest, (c) bounded — at most ONE parse-retry on malformed output, then
graceful degradation to a deterministic fallback, never an "ask the model to
fix it" loop. Ingest specifically makes ZERO model calls: outline comes from
PDF bookmarks first, fixed page-windows as fallback.

## Data model law

1. **Source and generated content never share a column.** `Chapter.body_md` is
   immutable extracted text; ALL generation paths (initial, lazy, regenerate)
   write only `lesson_md` + `lesson_status`. Enforce with a DB-level trigger or
   an ORM validator that raises if `body_md` changes after insert — not just
   convention.
2. **Every table that references course_id/section_id registers itself for
   cascade.** Maintain one `DERIVED_TABLES` registry; re-ingest and delete-course
   both iterate it (re-ingest replaces, never appends). A single test asserts
   the registry covers every FK-bearing model via metadata reflection, so adding
   a table without registering it fails CI automatically.
3. **Section and card identity is content-addressed.** `section_id =
   hash(normalized source text)`. On re-ingest, unchanged sections keep their
   id, and ReviewState/ReviewLog/ProgressState rows survive by remap; only
   rows whose section hash disappeared are deleted. Tests: re-ingest of an
   identical PDF loses zero review state; re-ingest with one changed chapter
   resets only that chapter's state. (User learning history is core product
   value — never wipe it wholesale.)
4. **Identifiers crossing layer boundaries are opaque.** Citation refs like
   `"{section_id}:p.N"` are display-only; nothing ever parses them back.
   Structured fields travel alongside when navigation is needed.
5. **Schema changes only via Alembic revisions.** Startup handles fresh /
   pre-migration / managed DBs through one `init_db()` — never raw `create_all`
   on an existing DB.

### SQLite operating rules

- Open every connection with `PRAGMA foreign_keys=ON`, WAL mode, and a
  busy_timeout. Declare `ON DELETE CASCADE` on every FK so delete-course is
  DB-enforced; the `DERIVED_TABLES` registry remains only for re-ingest
  (replace-not-append is app semantics, not deletion).
- One-writer discipline: the API process and job worker both write, so every
  job claim uses an atomic
  `UPDATE ... SET status='running', lease_until=... WHERE id=... AND status='queued' RETURNING id`
  — no read-then-write claims.

## LLM layer (own it in one place)

- One provider abstraction. Concurrency limiting lives ONLY inside provider
  `complete()`/`embed()` via a single `llm_slot()` context manager. No
  semaphores anywhere else — nested gates caused a real deadlock in v1. When
  slots saturate, fast-fail 429 to the caller rather than blocking silently.
- Retry ONLY transient errors (timeout / connection / 5xx). Never retry 4xx —
  it double-bills and cannot succeed. One shared `_is_transient()` predicate.
- Model output is untrusted input: parse defensively, and on failure degrade
  per-item (one bad quiz question dropped ≠ whole course failed). Any batch
  operation isolates per-item failures — one bad PDF must not fail the course.
- Embeddings are nullable in the schema and every retrieval path skips nulls.
- Prompts live in versioned files (even `prompts/v1/*.md`), not inline strings.
- **LLM call ledger.** Every provider call writes one row: timestamp, purpose,
  model, input/output tokens, latency, cost estimate, prompt_version,
  success/parse-failure. Generated content rows carry the prompt_version that
  produced them (staleness = `row.prompt_version < current`). Optional
  per-course spend cap that fails generation jobs cleanly when exceeded.

## Jobs & durability (build in week 1, not as debt)

- Long-running work goes through a Job table (id, type, status, payload,
  heartbeat/lease) + a worker loop — NOT framework background tasks, which die
  with the process. Every status a job can hold is either terminal or has a
  reconciler rule: on startup, stale in-flight jobs are failed-over or resumed.
  Rule: "no status string exists without a restart story."
- Progress streams to the frontend via SSE from day one; no client polling.

## Config & environment

- All config read lazily through one `config.py` accessor at call time. Never
  snapshot `os.environ` at import — tests monkeypatch env after import.
- Runtime data lives in `data/`, gitignored from the first commit.
- **Data safety.** Nightly SQLite backup (`VACUUM INTO`) to `data/backups/`,
  retain N. One-click export of a course to a zip of Markdown + assets — the
  reader's content must never be hostage to the app.

## Frontend

- TypeScript + client generated from the backend's OpenAPI schema from day
  one. No hand-written fetch shapes.
- One API module is the only fetch boundary. One shared SSE/polling hook. One
  shared Chat component whose callbacks the call site memoizes (document this
  in the component). Scroll containers manage their own overflow — never
  scroll the document to track a child list.
- Errors surface through one ErrorBanner using status codes to distinguish
  retryable from terminal.

## UX law

**Design target: minimize friction in the daily loop (open → resume → read →
review → close), not feature count.** v1's UI was CRUD-shaped, not
study-shaped — screens existed but every loop step had friction.

1. **Outline is user-correctable.** After ingest, the ToC is editable: rename,
   merge, split, reorder, delete chapters. Derived data (chunks, cards,
   lessons) re-derives lazily for affected sections only. The upload flow
   shows the detected outline for confirmation before finishing — one screen,
   skippable, defaults accepted on Enter. (A wrong outline poisons everything
   downstream; the page-window fallback in particular will sometimes be wrong.)
   Note: merge/split changes content hashes and resets review state for the
   affected sections — say so in the UI.
2. **Resume everywhere.** Last chapter + scroll position persist server-side
   per course. Dashboard leads with a "Continue" card (course, chapter, %).
   Review sessions resume mid-queue after close.
3. **Keyboard-first study surfaces.** Reviews: Space reveals, 1–4 grade.
   Reader: ←/→ or j/k chapter nav, shortcut to toggle source/lesson. Visible
   hint row on each surface; shortcuts listed under "?".
4. **Generation is transparent and non-blocking.** Before: show estimated
   time and cost (from the ledger's rolling averages). During: stream
   section-by-section over SSE — the user reads finished sections immediately;
   never a bare spinner. After: content labeled as generated, with model +
   prompt version and a Regenerate affordance. Source text is always readable
   regardless of generation state.
5. **Citations navigate.** Chat responses return structured citation fields
   (section_id, page) alongside the display ref; clicking jumps to that
   chapter anchored at the page. The display string stays opaque.
6. **The reader is a reading product.** Light + dark via
   `prefers-color-scheme` with a manual toggle; user-adjustable font size,
   measure (column width), and line-height, persisted. Footnote/heading
   anchors deep-linkable.
7. **Review health is visible.** Due-count badge in nav; backlog warning when
   due > daily throughput; session-size chooser ("Review 10 / 25 / all").
   Graded tests show per-question review with explanations, not just a score.
8. **No dead ends, no wedges.** Every async state has: progress with a
   human-readable stage, a timeout that degrades to "still working — check
   Jobs" with retry, and a per-item failure badge (one failed PDF never blocks
   the course view). Every empty state names the next action.
9. **First-run teaches by doing.** Bundled sample course on first launch;
   drag-and-drop upload anywhere on the dashboard.
10. **Accessibility floor.** Full keyboard operability, focus management on
    route change, WCAG AA contrast in both themes, reduced-motion respected.

Phase-2 backlog (deliberately not in scope): highlights/annotations that
become SRS cards (killer feature candidate, real scope — do it whole or not at
all), chat search, command palette, mobile polish beyond nav correctness.

## Security

- Any user-supplied URL fetch goes through one SSRF-guarded fetcher (deny
  private ranges, resolve-then-connect). File uploads validated by content
  sniffing, size-capped, stored outside the web root.

## Testing law

- Tests get an isolated temp DB via env override; LLM/network is ALWAYS
  mocked — a test that touches the network is a bug. Provide the stubbing
  helpers in conftest from the start.
- Every invariant above gets a named regression test when introduced (e.g.
  `test_reingest_replaces_not_duplicates`,
  `test_generation_never_touches_body_md`).
- **Extraction fixture corpus.** Maintain `tests/fixtures/pdfs/` covering:
  bookmarks present, no bookmarks, scanned/no-text-layer, encrypted, huge
  (500+ pages), non-English, malformed/truncated. Golden-snapshot tests assert
  outline structure and extracted-Markdown stability; an extractor bump
  requires regenerating snapshots in the same PR (visible diff = reviewable
  quality change). Stamp `extractor_version` on chapters so upgrades can
  selectively re-extract.
- **Invariants as executable checks.** `tests/test_architecture.py` enforces
  the laws mechanically: no semaphore imports outside `llm/`, no `os.environ`
  reads at module scope, no inline prompt strings in pipeline modules, routers
  import services only (use import-linter or AST greps). The brief's rules
  fail CI, not code review.
- One `build.sh` = compile + backend tests + frontend typecheck/build; CI runs
  exactly that script, no drift. Frontend gets at least component tests for
  the reader and chat.

## Process

- Keep `docs/decisions.md` as an append-only ADR log; any reversal of a rule
  in this brief requires an ADR explaining what changed.
- Routers stay thin (existence checks + delegation); business logic in
  pipeline/service modules. Shared helpers get extracted, not duplicated —
  but don't force module splits that create artificial third homes.
- **Definition of done per phase:** named regression tests for new invariants,
  an ADR for any deviation from this brief, and a 5-minute manual smoke of the
  end-to-end flow.

## Build order

- **Phase 0 — walking skeleton.** Repo scaffold, CI running `build.sh`, one
  health endpoint, one page rendering from the generated API client, Job table
  with a no-op job executing end-to-end. Every later phase lands on green CI.
- **Phase 1** — schema + Job worker + config + test harness.
- **Phase 2** — ingest + extraction + reader (fully usable with zero LLM).
- **Phase 3** — LLM layer + lazy lesson generation.
- **Phase 4** — SRS + chat.

Ship each phase working end-to-end.

## Appendix: v1 pitfalls each rule prevents

| v1 bug / debt | v2 rule |
|---|---|
| Generated lesson overwrote `body_md`, destroyed source text | Data law 1 (+ trigger/validator enforcement) |
| Re-ingest duplicated outline; delete-course orphaned Chunk/ReviewLog/TestAttempt | Data law 2 registry + reflection test; SQLite FK cascade |
| Re-ingest wiped user's SRS history | Data law 3 content-addressed identity |
| Router + provider semaphores → double-acquire deadlock | LLM layer single `llm_slot()` |
| 4xx retried → double-billing | Transient-only retry |
| Env snapshot at import broke test monkeypatching | Lazy config accessor |
| One bad PDF / one parse error failed the whole course | Per-item failure isolation |
| Null embeddings broke retrieval | Nullable embeddings, skip in retrieval |
| Background tasks died with process, wedged the UI | Job table + reconciler ("no status without a restart story") |
| Chat auto-scroll scrolled the document | Scroll-container rule |
| SSRF on URL fetch | SSRF-guarded fetcher |
| Hand-written fetch shapes needed response guards | OpenAPI-generated TS client |
| Polling everywhere (known debt #3) | SSE day one |
| Durable queue never built (debt #1) | Jobs in week 1 |
| No cost visibility despite cost being a core goal | LLM call ledger |
| Blind 30–60s generation waits, no resume, mouse-only reviews | UX law 2–4 |

Honest remainder no brief prevents: extraction-quality tuning, SRS scheduling
feel, prompt quality — found only by running. The fixture corpus and ledger
make them measurable, not absent.
