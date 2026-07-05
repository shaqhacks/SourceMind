# Decision Records

Append-only. Each entry: context → decision → consequences. Dates are when the decision landed.

## ADR-001: `lesson_md` is the sole generated-content column (2026-07-04)

**Context.** Two generation paths diverged: initial generation wrote `lesson_md`, regeneration wrote `body_md` — clobbering immutable source text and serving stale lessons.
**Decision.** `body_md` = extracted source, never rewritten after ingest. All generation (initial, lazy, regenerate) converges on `generate_lesson`, writing `lesson_md`/`lesson_status`. Regenerate = `generate_lesson(force=True)`.
**Consequences.** One code path to maintain; readers pick `lesson_md` when ready, else `body_md`. Any new generation feature must extend `generate_lesson`, not fork it.

## ADR-002: Deterministic code before model calls (2026-07-04, owner directive)

**Context.** Owner explicitly prefers scripts/code over LLM calls: cheaper, and same input → same output.
**Decision.** Validation gates (word count, quiz presence), parsing, ranking, chunking are deterministic. LLM calls are minimized: grounding check skipped on repair rounds once passed; at most one parse-retry when structured output is unusable; embeddings batched.
**Consequences.** When adding pipeline steps, budget LLM calls explicitly and prefer a rule over a judge. A "have the model verify" loop needs justification.

## ADR-003: Re-ingest is destructive replace (2026-07-04)

**Context.** Re-uploading a course duplicated the entire outline; derived rows (reviews, chats, attempts, progress) referenced section_ids that no longer existed.
**Decision.** `_finish_ingest` deletes every derived row for the course before inserting the fresh outline.
**Consequences.** Re-ingest loses user progress by design — acceptable for a local-first tool where re-ingest means "the source changed". A future "preserve progress across re-ingest" feature needs section-id stability first.

## ADR-004: Alembic with three-path startup (2026-07-04)

**Context.** Schema evolved via `create_all`, which never alters existing tables — new columns silently missing on old DBs.
**Decision.** Alembic under `backend/db/migrations/`. `init_db`: fresh DB → create_all + stamp head; tables-but-no-alembic_version → stamp baseline + upgrade; managed → upgrade. Explicit-engine test path keeps fast create_all + stamp.
**Consequences.** Every model change ships a revision. SQLite ALTERs use batch mode. Baseline (0001) is hand-written — never regenerate it.

## ADR-005: LLM concurrency gate lives in the provider layer (2026-07-04)

**Context.** Router-level semaphore covered chat + generation but not ingest or lazy lessons; blocking semaphore in handlers tied up workers.
**Decision.** Single `llm_slot()` BoundedSemaphore in `backend/llm/limiter.py`, acquired inside every provider `complete()` and embed call. Router-level acquisitions removed.
**Consequences.** Uniform enforcement, no bypass. Two costs accepted: (a) saturated requests now block rather than fast-fail 429 — revisit if chat hangs under load; (b) nested provider calls while holding a slot would deadlock — never call a provider from code inside a slot.

## ADR-006: Transient-only retry (2026-07-04)

**Context.** Retry wrapper retried everything, including 400/401 — double-billing on calls that could never succeed.
**Decision.** `_is_transient` gates retries: timeout/connection/5xx only, exponential backoff + jitter. 4xx raise immediately.
**Consequences.** New error types must be classified deliberately. Rate-limit (429) is currently NOT retried — deliberate scope cut, revisit with provider-native retry if it bites.

## ADR-007: Section-aware chunking, opaque source_ref (2026-07-04)

**Context.** Fixed 350-word windows straddled chapter boundaries; citations couldn't name a section.
**Decision.** Chunk within each section's page range; `source_ref = "{section_id}:p.N"`. Frontend treats it as display-only text. Whole-doc windowing remains the no-sections fallback.
**Consequences.** Citations map to real sections. The ref format is changeable in one place as long as nothing starts parsing it.

## ADR-008: Skip the ingest/generation service split (2026-07-04)

**Context.** service.py ~1000 lines; a split into ingest.py/generation.py was considered.
**Decision.** Skipped: shared helpers (page cache, source-text rebuild, asset URLs) are used by both halves — a split forces a third shared module or cross-imports. Extracted `_plan_record`/`_asset_records`/`_seed_review_states`, moved chat to `pipeline/chat.py` and grading to `services/grading.py` instead.
**Consequences.** service.py stays big but sectioned. Revisit only when a clean seam appears (e.g. durable job queue naturally pulls generation out).

## ADR-009: Frontend stays plain JS for now (2026-07-04, deliberate deferral)

**Context.** No type contract with the backend caused shape-guessing (`c.id ?? c.course_id`) and field disagreements between pages.
**Decision.** Deferred TypeScript + OpenAPI codegen (top of debt list). Interim: `api.js` is the single fetch boundary, `id` is the canonical course field, polling via `usePolling`, chat via shared `Chat` component with memoized function props.
**Consequences.** Response-shape drift is still caught only at runtime. First structural frontend investment should be the typed client — it deletes the guard idioms wholesale.

## ADR-010: Zero-LLM ingest — bookmarks, page windows, lazy per-chapter refinement (2026-07-05, owner directive)

**Context.** Ingest ran an LLM outline pass (`detect_outline`, chunked over the whole book) whenever a PDF had no usable embedded TOC, plus an unconditional `generate_plan` LLM call for objectives/importance/prerequisites — even though chapters are read instantly from `body_md` and lessons are opt-in (2026-07-04 lazy-ingest pass). Testing against a real textbook (a 489-page open algebra text with zero embedded PDF bookmarks — confirmed via `fitz.Document.get_toc()`) showed ingest falling through to the slow whole-book LLM outline path every time, directly contradicting the owner's cost/determinism preference (ADR-002) and the goal of upload being as fast as possible.
**Decision.** Ingest now makes **zero** LLM calls, full stop:
- **Bookmark-first outline** (`sections_from_toc`): if a PDF has embedded bookmarks, picks the *deepest* level whose entry count falls in `[4, 80]` (not just the shallowest level) so a "Part"-level wrapper with 2 entries doesn't shadow a usable "Chapter" level underneath it.
- **No-bookmark fallback = deterministic page windows** (`sections_from_page_windows`), not LLM: fixed-size windows (`SOURCEMIND_FALLBACK_PAGES_PER_CHAPTER`, default 15) titled "Pages A-B". `detect_outline` is no longer called anywhere in ingest.
- **`default_plan`** replaces `generate_plan` at ingest: objectives=[], importance="supporting", prerequisites=[], `target_words` still computed deterministically from real source word counts (same arithmetic `generate_plan` used, `compute_target_words`).
- **Lazy per-chapter metadata fill** (`ensure_plan_metadata`, wired into both `ensure_study` and `generate_lesson`): one bounded LLM call scoped to *that chapter's own source text* fills real objectives/importance (and recomputes `target_words` for the newly-known importance) on first use. Cross-chapter `prerequisites` need whole-outline context to infer meaningfully and are deliberately left `[]` even after this fill.
- **Lazy placeholder-title refinement** (`maybe_refine_title` / `run_title_refinement_job`, wired into the `get_chapter` and `study` routers): a page-window chapter's "Pages A-B" title is refined via one bounded LLM call the first time that chapter is read, as a non-blocking background task. `Chapter.title_status` (migration 0003) tracks this: `None`/`"toc"` = authoritative, `"placeholder"` = needs refinement, `"refining"/"refined"/"failed"` mirror the existing `lesson_status` state machine, including `reconcile_interrupted_jobs()` failing over a stuck `"refining"` row on restart.
- **Front matter is never folded into "chapter 1"** (`carve_front_matter`, `detect_front_matter_pages`). Owner live-testing the real algebra textbook against the running dev server found its page-window "chapter 1" contained the title/copyright/dedication/printed-TOC pages that precede the real Chapter 0 content. Confirmed by hand against the PDF (pages 0-5 are front matter; real content starts on page 6) and, separately, that this book's absent bookmarks are not a level-selection bug: `fitz` reports `get_toc()` (`simple=True` and `False`) empty, `doc.outline` is a null stub, and a brute-force scan of every xref in the file found no `/Outlines` object at all — the Ghostscript/TeXmacs pipeline that produced this PDF never embedded one. Each outline source gets its own front-matter boundary: a bookmark outline's first chapter's own `page_start` (whatever precedes it is front matter by definition, no heuristic needed); the page-window fallback (whose first window always starts at page 0 regardless of content) instead uses a deterministic keyword/dot-leader-line regex heuristic (`detect_front_matter_pages`) scoped to the leading run of pages only. The carved-out "Front Matter" chapter is real (readable body_md, `importance="peripheral"`) and needs no title refinement (`title_status=None`).
**Consequences.** Upload is now genuinely instant regardless of provider latency or book length — even a book with zero bookmarks never touches the LLM until a chapter is actually opened. `detect_outline` and `generate_plan` (title-only prompt, whole book) are no longer called anywhere in production; kept for their existing test coverage and as a possible building block for a future "reprocess this course's whole outline" admin action — the per-chapter lazy fill deliberately does NOT reuse `generate_plan`'s prompt, since a placeholder page-window title carries no topical signal for a title-only prompt to work with, whereas the lazy fill reads the chapter's actual source text. The front-matter heuristic is deliberately conservative: a bare title page with no boilerplate keyword at all (no "Copyright"/ISBN/dedication marker) is a known, accepted miss — a low-word-count/sparse-page fallback was tried and reverted because it false-positived on legitimately short real content pages, which is a worse failure mode than an occasional unlabeled title page staying folded into chapter 1.

## ADR-011: Layout-aware Markdown extraction via pymupdf4llm (2026-07-05, owner-reported)

**Context.** Owner reported that extracted chapter text (`Chapter.body_md`, plain `page.get_text("text")`) reads badly: no real headings, hard line breaks mid-paragraph, no list structure — "ugly markdown," far from the source PDF's reading fidelity.

**Decision.** `extract.pdf.extract_pdf` now sources page text from `pymupdf4llm.to_markdown(doc, page_chunks=True, write_images=False, table_strategy=None)` instead of `page.get_text("text")`, with two deliberate, measured deviations from pymupdf4llm's own defaults:
- **`pymupdf4llm.use_layout(False)`** forces its classic heuristic converter (font-size → heading level, PyMuPDF's own block/line grouping for paragraph reflow) instead of the ML/OCR layout engine it defaults to when `pymupdf-layout` is importable — which it always is, since that package is a *hard, version-locked dependency* of `pymupdf4llm` (`pymupdf4llm==1.28.0` requires `pymupdf==1.28.0` and `pymupdf_layout==1.28.0` exactly; a mismatched trio raises `ImportError` at `import pymupdf4llm` time). The ML path pulls in onnxruntime and OCR and is unnecessary for born-digital textbook PDFs — it's never invoked, only imported (a measured ~0.17s cost).
- **`table_strategy=None`** disables grid-table detection. Measured on the owner's real 489-page open algebra textbook (zero embedded bookmarks, the same book ADR-010's front-matter carving was validated against), this cut whole-book conversion from 32.0s to ~19.7s with no loss of real tables — this book has none.

Both numbers matter against the ~30s ingest-latency budget implied by ADR-010: the *default* pymupdf4llm path (ML layout engine, table detection on) measured over that budget; the tuned path measured safely under it, so `body_md` still gets built eagerly for every chapter during ingest (as it always has) rather than needing a new lazy-conversion mechanism that would have put `Chapter.body_md`'s "immutable, set once at ingest" invariant (CLAUDE.md #1) at risk.

**Math rendering — the one real regression, and how it's contained.** pymupdf4llm's classic converter infers `<sup>`/`<sub>`/`<u>` spans from a text span's baseline offset relative to its line. Textbook PDFs render division/fraction problems as a vertically-stacked numerator / division-bar / denominator, which this heuristic misreads as one of those spans. Verified against the real book: this isn't a rare corner case for an algebra text — it fires throughout the fractions-practice chapter (every single exercise) and throughout equation-solving worked examples (the division step of nearly every two-step-equation example), i.e. exactly the pedagogically central content. Because the frontend renders raw HTML embedded in Markdown (`react-markdown` + `rehype-raw`), an unstripped tag doesn't stay inert — it renders as a visibly broken, disconnected underline/superscript in the reader. `extract.pdf._SPURIOUS_TAG_RE` strips `<u>`/`</u>`/`<sup>`/`</sup>`/`<sub>`/`</sub>` (keeping their inner text) as a deterministic post-processing pass. This doesn't recover the lost fraction bar — the numerator and denominator still land on consecutive lines, exactly as ambiguous as plain-text extraction already was for the same problem — but it removes the visibly-broken-HTML failure mode, bringing the worst case back to parity with plain text instead of a regression. Verified before/after against the same real pages.

**Consequences.** `body_md` gains real headings, bold callout labels, reflowed paragraphs, and (a bonus found during verification) correctly-decoded ligatures ("first" instead of plain-text's broken "ﬁrst") for the large majority of a textbook's prose content, at no cost to math-heavy pages beyond what plain text already cost them. `SOURCEMIND_PDF_MARKDOWN` (`config.pdf_markdown_extraction()`, default `true`) is the owner-facing escape hatch to plain text if a future book's math-notation tradeoff doesn't hold even after tag-stripping. Conversion failure, a missing/version-mismatched pymupdf4llm install, or a returned chunk count that doesn't match the page count all fall back to plain text automatically and unconditionally (`extract.pdf._markdown_pages` never raises) — regardless of the config flag's value, so a broken pymupdf4llm install can never fail ingest over formatting. The front-matter keyword/dot-leader heuristic (ADR-010) was verified unchanged against the real book (identically 6 front-matter pages fed plain text vs. Markdown); the keyword check was additionally hardened to strip `*`/`_` emphasis markers before matching, in case a future book's converter output bolds a multi-word keyword phrase (e.g. "table of contents") word-by-word rather than as one run.
