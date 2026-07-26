# SourceMind v2 — Decision Log (append-only)

Any reversal of a rule in `v2-build-brief.md` requires an ADR here explaining
what changed (brief: Process).

## ADR-001 — v2 lives in `smv2/` inside the SourceMind repo (2026-07-05)

Greenfield rebuild shares the repo with v1 rather than a new repository:
shared git history and issue context, one CI home, and v1 stays runnable
side-by-side during the rebuild. CI for v2 is a separate workflow
(`.github/workflows/smv2-ci.yml`) path-filtered to `smv2/**`.

## ADR-002 — uv + `pyproject.toml` is the single backend dependency source (2026-07-05)

v1 used `backend/requirements.txt`. v2 uses a uv-managed `pyproject.toml`
(+ lockfile) as the one source of truth: pinned, reproducible installs and one
command (`uv sync`) in dev and CI. The v1 rule's intent — exactly one place
declares dependencies, never `--with` lists in scripts — carries over intact.

## ADR-003 — Job worker is an in-process asyncio task over a durable Job table (2026-07-05)

The brief requires a Job table + worker loop, not a specific process topology.
Single-user laptop deployment favors one process. Durability comes from the
table + startup reconciler ("no status without a restart story"), not process
lifetime. Claims are atomic single-statement UPDATE…RETURNING with leases, so
a separate worker process remains a drop-in change if concurrency ever needs it.

## ADR-004 — `openapi.json` and generated TS types are committed artifacts (2026-07-05)

`build.sh` regenerates the OpenAPI schema and `frontend/lib/api/schema.d.ts`
on every run. Committing them makes API drift visible in diffs and lets the
frontend build without a running backend. The backend remains the source of
truth; hand-editing generated files is a bug.

## ADR-005 — Prompt delivery: instructions in system, source in tagged user content (2026-07-05)

Extracted PDF text is untrusted input interpolated into prompts. All
generation paths send instructions via the provider `system` parameter and
source material inside `<source_text>`/`<excerpts>` tags in the user message,
with the prompt instructing the model to treat tagged content strictly as
material. Structural mitigation, not a guarantee. Prompt files live in
`backend/prompts/vN/`; restructuring delivery without changing prompt text
does not bump the version.

## ADR-006 — Spend cap is a safety net with bounded overshoot, not billing enforcement (2026-07-05)

The per-course cap is checked immediately before each provider call and
re-checked after; overshoot is bounded by `llm_max_concurrency()` in-flight
calls. Hard atomicity over SQLite for an estimate-based cap was judged not
worth the locking complexity. The sequential worker makes the batch
(generate-all) case airtight, which is the realistic overspend scenario.

## ADR-007 — SM-2 bootstrap intervals extended to Hard/Easy (2026-07-05; corrected 2026-07-06 to match implementation)

Classic SM-2 only defines first-review intervals for Good. A card first
graded Hard or Easy would otherwise multiply interval 0 forever. As
implemented (`srs_service.py`): the first two non-Again reviews use fixed
baselines of 1d then 6d for Hard/Good/Easy alike; Easy applies its 1.3×
bonus on top of the baseline; the ease multiplier is skipped entirely until
reps ≥ 2 (ease is unproven early), and ease adjustments always take effect
the following review, not retroactively. Again: 10min due, reps reset,
lapse counted, ease −0.2 floored at 1.3. Full table in `test_srs_schedule`.
(Correction note: the original ADR text said "Easy 4d ease-adjusted" — that
never matched the code; this is a documentation fix, not a behavior change.)

## ADR-008 — Chat is synchronous; generation is jobs (2026-07-05)

Lesson/cards/quiz generation runs through the durable Job table (long,
restart-safe, SSE progress). Chat is a synchronous request/response: latency
budget is one completion, and fast-fail 429 from the limiter plus 504 on
provider timeout give the client honest, retryable signals. Chat turns
persist atomically only when the exchange succeeds — a failed reply leaves no
orphaned user turn.

## ADR-009 — SSRF guard built before any URL-fetch feature exists (2026-07-05)

`app/security/fetch.py` (scheme allowlist, resolve-then-check against
private/loopback/link-local/metadata ranges, size+timeout caps) is currently
uncalled by product code. It exists so the blessed path predates the feature,
and an architecture test confines httpx to `app/llm/` and `app/security/` so
any future URL fetch must go through it. Known limitation, documented in the
module: check-then-connect is not IP-pinned; tighten to a pinned transport
when a real caller lands.

## ADR-010 — Embeddings: Ollama-only, nullable, lazily backfilled (2026-07-05)

Anthropic has no embeddings API, so `AnthropicProvider.embed` raises
NotSupported and retrieval degrades to deterministic lexical ranking.
Embeddings backfill lazily (first chat triggers `embed_course`), per-chunk
failures stay NULL and are always skipped by the vector path. Chat therefore
works with zero embedding infrastructure, better with Ollama present.

## ADR-011 — Quiz generation input is course-scoped but bounded (2026-07-06)

Cross-section assessment is the feature's purpose: a quiz is meant to test
understanding across multiple chapters, not one section at a time like
lessons/cards. This deviates from the brief's "never a whole-book call"
letter — quiz generation can be handed the entire course's sections — but
input is capped at 24k combined characters via proportional per-section
heads regardless of book size, so every call remains bounded, single, and
never scales with book length. The letter (never whole-book) is deviated
from; the spirit (bounded cost, one call) is honored.

## ADR-012 — Generation streaming granularity is per-section (2026-07-06)

The brief's "stream section-by-section over SSE; the user reads finished
sections immediately" is implemented at section granularity: per-section
jobs flip that section readable one-by-one over SSE as each completes, and
within a single section's generation the UI shows staged progress (never a
bare spinner). Token-level streaming inside one section's own completion
call is explicitly out of scope. Chat citations are section-granular today
even though `Chunk.page` exists in the schema unused by navigation —
page-level citation jump is phase-2 polish, not a Phase 4 gap.

## ADR-013 — Deterministic front-matter skipping in ingest (2026-07-06)

Real-world PDFs ingested chapters that were actually front matter — title
pages, publisher/copyright pages, tables of contents — because nothing in
`app/pipeline/outline_detect.py` distinguished them from real chapters. The
fix stays inside ingest's zero-LLM prime directive: two narrow, deterministic
signal sets, one per outline path.

Bookmark path: a bookmark title denylist (`^(table of )?contents$`,
`^copyright( page)?$`, `^title page$`, `^colophon$`, `^dedication$`,
`^acknowledgm?ents?$`, matched case-insensitively) drops matching bookmark
entries before section bounds are built; content before the first surviving
bookmark's page was already excluded by the existing algorithm (bounds start
at the first chosen entry's own page) and needed no new code. The denylist
is deliberately narrow — preface, foreword, introduction, and index are
never dropped, since those routinely contain real, citable content and a
false positive there is worse than an occasional missed front-matter page.

Page-window fallback: before windowing, scan at most the first 10 pages and
skip while a page matches any of — a copyright/ISBN signal, a page shaped
like a table of contents (≥40% of its non-empty lines end in a page number,
minimum 5 such lines), or near-empty (<120 chars). If the 10-page scan
window never finds a page that clears all three signals, the skip is 0
(never blindly consumes the whole scan window) — this is a deliberate
false-positive guard: several existing fixtures (`huge.pdf`'s 520 tiny
pages, `non_english.pdf`'s 2 short pages, `scanned.pdf`'s empty pages) would
otherwise have some or all of their real content skipped.

Both paths are gated by `skip_front_matter()` (`SMV2_SKIP_FRONT_MATTER`,
default on) for an escape hatch if the heuristics misfire on a real course.
Dropped bookmark titles are logged via the ingest job's progress message so
the user can see what was skipped. The outline-confirmation/edit screen
remains the user's correction point for anything the heuristics get wrong in
either direction. `_EXTRACTOR_ALGO_VERSION` bumped to `algo-2`; the
`with_bookmarks`/`no_bookmarks`/`non_english` golden snapshots are
unaffected (verified byte-identical after regeneration — none of those
fixtures contain front matter).

## ADR-014 — Outline confirmation screen removed from the upload flow (2026-07-06)

The brief's UX law 1 mandated a skippable outline-confirmation screen between
ingest and reading. Owner testing found it added friction without value once
outlines carry real chapter names: verifying page numbers is not a user job.
Upload now lands directly in the reader (auto-accept). Outline editability —
the substance of law 1 — is preserved and relocated: the same editor
(rename/reorder/delete/merge/split, with the review-state-reset warning)
opens from the reader's TopBar and the "o" shortcut, operating on the live
outline via the existing edit_outline endpoint. The heading-detection outline
tier (ADR-013 successor work, algo-3) is what makes auto-accept reasonable:
detected chapter titles replace page-window ranges as the default outline.

## ADR-015 — Heading-detection middle tier: bookmarks -> headings -> page windows (2026-07-06)

A page-window fallback alone regularly slices mid-chapter for a real book
with no usable bookmarks — a chapter boundary lands inside a fixed-size
window instead of at its own page, producing titles like "pages 61-72" that
actually span 3 chapters. `app/pipeline/outline_detect.py::sections_from_headings`
adds a deterministic middle tier, still inside ingest's zero-LLM prime
directive: it detects chapter boundaries from large-font lines read straight
off the PDF's raw page dict (`app/pipeline/extract.py::extract_heading_candidates`
— per-line size/bold/text, no pymupdf4llm/markdown involved) before falling
all the way back to fixed windows.

A line qualifies as a heading candidate if its font size is >= 1.25x the
document's body size (body = the rounded font-size bucket with the most
total characters, i.e. modal size weighted by text length) — or >= 1.1x
when it matches a "Chapter N" / numbered-heading shape — its stripped length
is 3-80, it doesn't end in `.,:;` (excludes a large-font pull-quote or
epigraph), and it isn't mostly digits (excludes a running-header page
number). Qualifying lines are grouped into tiers by rounded font size (a
document's different heading levels); the largest tier producing a
plausible outline (3-80 sections spanning >=60% of the document) wins — a
single oversized one-off (e.g. a cover-page title) doesn't win just for
being biggest, since its tier has only 1 candidate. When two headings in
the winning tier share a single page (page granularity can't split any
finer), the first claims that page as its section start; the second is
bumped to the very next page rather than dropped, so both still surface as
distinct, correctly-ordered sections. Detected heading titles are cleaned
(whitespace collapsed, a trailing dot-leader run stripped) and pass through
the SAME front-matter denylist as bookmark titles (ADR-013) — a detected
"Table of Contents" heading is dropped exactly like a ToC bookmark would be.
ADR-013's leading-front-matter-page skip applies before heading detection
runs, using the identical `first_content_page_index` signal the page-window
fallback already used.

Tier order is bookmarks-first, unconditionally: heading detection only runs
when bookmarks yield fewer than the usable-section minimum, so a real ToC
(however sparse) is always trusted over inferred font-size boundaries.
`_EXTRACTOR_ALGO_VERSION` bumped to `algo-3`; the `with_bookmarks`/
`no_bookmarks`/`non_english` golden snapshots are unaffected (verified
byte-identical after regeneration), and a new `headings_no_bookmarks`
snapshot fixture (4 chapters, no bookmarks, one same-page collision, one
punctuation-excluded trap) pins the new tier's own output.

## ADR-016 — Heading tier: scaled cap, union split, no-drop guard (2026-07-06)

Real-world testing against a 489-page textbook (Wallace, *Beginning and
Intermediate Algebra*) found ADR-015's tier selection picked the wrong
tier: the book's real structure was a 177-heading tier (chapter/lesson
titles, e.g. "Pre-Algebra - Integers"), but the fixed 80-section cap
rejected it outright, and a sparse, unrelated 5-heading tier (larger-font
"N.N Practice" worksheet headers) won instead — largest-size-first
iteration reaches the sparse tier before the real one, and it trivially
"qualifies" on the >=60% coverage check regardless of how little
structure it represents, because the last section always runs to the
document's final page by construction. The result: 5 sections, one
spanning 300 pages, with the book's first 31 pages dropped entirely.

Three changes to `sections_from_headings`, none reversing ADR-015's
tier-order or candidate-qualification rules, all tuning the
tier-*selection* step:

1. **Scaled cap.** The upper section-count bound is now
   `max(80, min(300, total_pages // 2))` instead of a fixed 80 — a
   489-page book scales to 244, comfortably admitting the real 177-heading
   tier. Never scales past 300 regardless of document length.
2. **Selection by section count, not size.** Among every tier whose own
   candidates independently pass the (3 to scaled-cap sections, >=60%
   coverage) check, the one with the MOST sections wins — not simply the
   largest font size. This is the actual fix for the real-book case: the
   177-heading tier now legitimately outscores the 5-heading one on its
   own merits, regardless of iteration order.
3. **Union split.** Once a tier wins, its final boundaries are the union
   of its own candidates and every candidate from a strictly LARGER tier
   (even one too sparse to ever win the standalone check) — a document's
   coarser heading level (chapter markers, or here the "N.N Practice"
   worksheet headers) still deserves to be a boundary alongside the finer
   winning tier, not discarded just because it lost the selection.
   Same-page collisions are resolved across the union exactly as within
   one tier.
4. **No-drop guard.** If the winning (unioned) tier's first boundary
   starts after the front-matter-adjusted first content page, a leading
   section is prepended covering that gap — titled after the longest
   heading-candidate line (from any tier, front-matter-denylist-filtered)
   sitting on the first content page itself, or "Introduction" if none
   does. Guarantees leading content pages are never silently dropped
   regardless of which tier wins.

Verified against the real textbook (kept locally, not committed):
181 sections, first section starts at page 1, largest single section
spans 8 pages, sample titles read "Pre-Algebra - Integers"-style — all
within the expected range. All existing fixture snapshots
(`with_bookmarks`/`no_bookmarks`/`non_english`/`headings_no_bookmarks`)
are unaffected (byte-identical after regeneration): none of their
candidate sets have more than one qualifying tier or a first-boundary gap,
so none of the four rule changes above have anything to act on.
`_EXTRACTOR_ALGO_VERSION` bumped to `algo-4`.

## ADR-017 — Practice/testing surface: section kind, chapter grouping, missed-question SRS (2026-07-06)

The owner's real textbook has per-chapter practice sheets ("0.1 Practice -
Integers") and an end-of-book answer key ("Answers - Chapter 8") mixed in
among ordinary chapter sections. Three deterministic additions turn that
structure into a chapters/testing/review surface, still inside ingest's
zero-LLM prime directive (classification is title-only, no LLM, no body
text inspection):

**Schema** (migration `0004_section_kind_chapter_label`): `sections.kind`
(`'content'|'practice'|'answers'`, default `'content'`) and
`sections.chapter_label` (nullable), `test_attempts.chapter_label`
(nullable, set only for a chapter-scoped test). No new FK-bearing table, so
no `app/db/registry.py` change was needed — `Section`/`TestAttempt` are
already registered.

**Classification** (`app/pipeline/outline_detect.py::classify_section_kind`/
`assign_chapter_labels`, computed per-asset during ingest so one PDF's
chapter numbering never leaks into another's in a multi-asset course):
`kind` from the title alone (`practice`/`exercise(s)`/`problems`/`review
questions` → practice; `^answers?` or `answer key` → answers; else
content). `chapter_label` is the exact title of the nearest PRECEDING
`^chapter N` marker section (a marker section labels itself); sections
before the very first marker backfill to that marker's title, so preamble
joins the chapter it introduces; a course with no chapter marker at all
gets `chapter_label=None` for every section (grouped client-side as "Front
matter"). Answer-key override: when a section's own title names a chapter
anywhere (e.g. "Answers - Chapter 8"), that reference wins over
position — answer keys cluster at a book's end and would otherwise all
inherit the LAST chapter's label. `_EXTRACTOR_ALGO_VERSION` bumped to
`algo-5`; the `headings_no_bookmarks` fixture gained a practice section and
an answer key (naming an earlier chapter) to exercise both the ordinary
and override paths in its golden snapshot; the other three snapshots
gained the two new fields with no value changes (verified byte-diff:
additions only).

**Chapters API** (`GET /api/courses/{course_id}/chapters`): sections
grouped by `chapter_label`, split into `section_ids` (content),
`practice_section_ids`, `answers_section_ids`, plus `test_stats` (attempt
count, best/latest graded score) from `test_attempts` grouped the same
way. The `chapter_label=None` group sorts first (labeled "Front matter"
client-side); everything else keeps course order.

**Chapter test mode**: `POST .../tests` gains an optional `chapter_label`
that resolves server-side to that chapter's practice+content section ids —
answer-key sections are excluded from every path that lets the SYSTEM
choose scope (chapter resolution here, and the pre-existing whole-course
fallback when neither `chapter_label` nor `section_ids` is given), since a
printed answer key in the prompt invites the model to copy its numbering
instead of writing real questions. A caller-supplied explicit `section_ids`
list is trusted as-is, unchanged from before. An unknown `chapter_label`
404s rather than silently falling back to a whole-course quiz.

**Missed → SRS** (`tests_service.submit_test`): each incorrectly answered
question becomes a `Card` (front = question + choices, back = correct
answer + explanation) via the existing content-addressed `card_id_for`, so
a repeated miss of the same question across attempts dedupes onto the same
card instead of violating its primary key. The target section is the
attempt's chapter's first practice section, else that chapter's first
section, else the attempt's own single-section scope, else the course's
first section. A brand-new card gets no `ReviewState` row at all — the
review queue already treats "no state" as "new" (and thus due), so nothing
further is needed for it to surface immediately. A card that already has
real SM-2 history (graded before, then missed again in a later test) only
gets `due_at` moved to now; ease/interval/reps are left untouched — a miss
on a test is evidence the card needs review, not a formal SM-2 lapse, and
only a real Again grade from the review queue should touch that state.
`submit_test`'s response gains `added_card_ids` (every card touched by this
submission's misses, whether newly created or refreshed).

## ADR-018 — Image extraction during ingest, LaTeX-aware prompts v2, narrower practice classification (2026-07-06)

Three independent, owner-approved changes landed together because the
first triggers an extractor-version bump the other two could ride along
with for one snapshot regeneration.

**Image extraction** (`app/pipeline/extract.py`,
`app/pipeline/ingest.py`, `app/services/images_service.py`,
`app/routers/images.py`): `pymupdf4llm.to_markdown(..., write_images=True,
image_path=..., filename=asset.id)` writes each embedded raster image to
`data_dir()/assets/{course_id}/images/` as
`{asset_id}-{page}-{index}.{ext}` — pymupdf4llm's own naming convention,
already deterministic (page + per-page index, no random component) as
long as a stable `filename` is passed in, which the asset's own id
provides for free. The markdown pymupdf4llm returns embeds the image's
*local filesystem path* inline as `![](...)`; `rewrite_image_refs_to_api_path`
rewrites that to `/api/courses/{course_id}/images/{basename}` before
`body_md` is normalized/hashed/persisted, since `body_md` is immutable
once a section exists (`smv2/CLAUDE.md` invariant #1) — this is the only
point the rewrite can happen. Re-ingesting the same course reproduces
identical rewritten text (same course_id, same deterministic filenames),
so content-addressed section identity is unaffected.

Per-image failure isolation required switching image-aware extraction to
PAGE granularity (pymupdf4llm exposes no finer-grained try/except point
than one `to_markdown()` call): if writing a page's image(s) raises for
any reason, that page is silently re-extracted with images disabled so
its text still lands, rather than losing a whole batch over one bad
image. Naively doing this per-page for every page turned out to cost
~15x on a large document — `IdentifyHeaders`, pymupdf4llm's whole-document
font-size histogram, is recomputed on *every* `to_markdown()` call by
default regardless of the `pages=` subset requested (the same
whole-document scan behavior the batched-extraction progress heartbeat
already relies on being byte-identical across page subsets), so 520
per-page calls each redid a 520-page scan. Computing it once
(`IdentifyHeaders(doc)`) and
passing it in via `hdr_info=` on every call — batched or per-page — drops
520-page per-page extraction from ~14.7s to ~0.8s, empirically verified
byte-identical output either way. `IdentifyHeaders` is not part of
pymupdf4llm's public API; the import is annotated with why and accepts
that a future refactor there breaks it loudly (ImportError) rather than
silently regressing performance.

Images directory is REPLACED-bucket semantics: wiped at the start of
every ingest run (before extraction begins, so it can't be an
after-the-fact cleanup step racing the new images being written) and
regenerated from scratch, so an asset removed or a shrunk image count
never leaves an orphaned file behind. This is a non-transactional
filesystem side effect done up front — same risk tolerance the ingest
loop already accepts for per-asset bookkeeping commits (see
`_extract_one_asset`'s own comment): if a later ingest stage fails, the
course lands in `ingest_failed` regardless, a state the user must already
recognize and retry, which repopulates images fully again. Course delete
needed no code change — the images directory is a subdirectory of the
course's assets dir, already covered by
`courses_service._remove_course_asset_files`'s existing `rmtree`.

`GET /api/courses/{course_id}/images/{filename}` (`get_course_image`)
serves only from that directory: a strict `^[A-Za-z0-9._-]+$` allowlist
rejects any path separator outright, plus an independent resolved-path
containment check, because a filename made entirely of dots (`".."`)
passes the allowlist regex on its own but would otherwise resolve to the
images directory's *parent* once joined and resolved — the regex alone is
not sufficient. `FileResponse` is given no explicit `media_type`, relying
on `mimetypes`' extension-based guess (pymupdf4llm's default format is
`.png`). `_EXTRACTOR_ALGO_VERSION` bumped `algo-5` → `algo-6`; a new
`images.pdf` fixture (one embedded solid-color raster, deterministic
pixel data, no bookmarks) exercises the whole path in its golden
snapshot; the other four snapshots were re-verified byte-identical when
routed through the same image-aware extraction call with zero images
present.

**Prompts v2** (`backend/prompts/v2/`): all four prompts (`lesson`,
`cards`, `quiz`, `chat`) gain one added rule — write math as LaTeX
(`$...$` inline, `$$...$$` display), never raw HTML — copied otherwise
unchanged from v1. `load_prompt`'s "always the highest `vN` present"
contract picks v2 up automatically. Expected and desired side effect:
every section with an existing `lesson_md` now reads `lesson_stale=true`
against the new prompt version (`parse_prompt_version` numeric comparison
against the section's stored `lesson_prompt_version`), nudging a
regenerate — the intended mechanism, not a bug.

**Classification narrowing** (`app/pipeline/outline_detect.py`,
supersedes ADR-017's classification rule): a real-book verification pass
against ADR-017's original regex found bare `problems` misclassifying
ordinary lesson titles ("Age Problems", "Distance, Rate, and Time
Problems") as practice sheets — a lesson misfiled as practice is worse
than a worksheet shown as content, so bare `problems` no longer counts on
its own. Final practice pattern: `practice | exercises? | problem sets? |
review questions | worksheets?` (added `worksheet(s)` as a new signal,
kept `problem set(s)` as the only way "problem(s)" still counts). Re-run
against the same real 489-page textbook: practice count dropped from 79
to 76, content rose from 91 to 94 (exactly the three reclassified
titles), answer-key count (11) and chapter count (11) unchanged. No
extractor-version bump needed on its own — classification is pure
title-metadata, not extraction — but folded into the same `algo-6`
snapshot regeneration since it was happening anyway.

## ADR-019 — Section→asset attribution + original-PDF serving endpoint (2026-07-06)

Owner request: the reader should be able to show a section's original PDF
page(s) alongside its extracted text/lesson. Two additions.

**`sections.asset_id`** (migration `0005_section_asset_id`, FK →
`assets.id` `ON DELETE SET NULL` — a section outlives its asset; deleting
the asset just disables the PDF view for sections that pointed at it, not
the sections themselves). Set at section creation in `ingest.py` (`item.asset.id`
is already in scope in the per-asset loop). Existing rows stay `NULL` until
their course is re-ingested — deliberately not backfilled retroactively;
`SectionOut`/`SectionDetailOut` both declare it nullable and every response
path was verified NULL-tolerant.

**SQLite migration gotcha, worth recording so it isn't rediscovered the
hard way**: adding a column with an inline FK constraint via plain
`op.add_column(..., sa.ForeignKey(...))` raises
`NotImplementedError: No support for ALTER of constraints in SQLite
dialect` — SQLite has no in-place ALTER for constraints at all; Alembic's
`batch_alter_table` is required, which performs the standard SQLite
workaround (build a new table, copy rows, drop the old one, rename the new
one into place). That rebuild **silently drops every trigger scoped to the
old table** — including `sections_body_md_immutable` (migration `0002`,
the very trigger enforcing `smv2-invariants`' body_md-immutability law).
Caught immediately by `test_body_md_immutable.py` going red across the
whole suite; the fix is recreating the trigger with the exact same `CREATE
TRIGGER` statement immediately after the `batch_alter_table` block, in
both `upgrade()` and `downgrade()`. Any future SQLite migration that uses
batch mode on `sections` must re-verify this trigger survives — it is not
protected by any schema-level dependency, only by remembering this note.

**`page_start`/`page_end` clarification** (not a change, a documentation
fix prompted by writing this ADR): these fields are 0-based internally
(`app.pipeline.outline_detect.SectionBounds`, `Section.page_start` column)
but `app.services.sections_service.to_display_page()` converts to 1-based
before they ever reach `SectionOut`/`SectionDetailOut` — the API response
value is already viewer-ready. `pdf.js` and most PDF viewers number pages
1-based, so a frontend consumer can pass `page_start`/`page_end` straight
into a viewer with **no further adjustment** — adding another `+1` "to be
safe" would double-offset it. Both schemas' docstrings now state this
explicitly since it's exactly the kind of detail a future refactor could
silently break in either direction.

**`GET /api/assets/{asset_id}/file`** (`get_asset_file`,
`app/services/assets_service.py::resolve_asset_file_path`): serves the
original uploaded PDF via `FileResponse`, `content_disposition_type="inline"`
(not the default `attachment`) so a browser embeds/views it instead of
downloading it, filename sanitized from `Asset.filename` and coerced to end
in `.pdf`. `Asset.stored_path` is server-minted at upload time
(`assets_service.save_upload`), never user input at request time, but the
resolver still asserts the resolved path stays under `data_dir()/assets`
before returning it — belt and braces, same posture as
`images_service.resolve_image_path`'s containment check (ADR-018) even
though the attack surface here is narrower (no user-supplied filename
component at all). 404 for both an unknown asset id and a row whose file
has gone missing from disk, distinguished internally
(`AssetNotFoundError`/`AssetFileMissingError`) but not to the caller — both
are just "can't serve this," and a caller has no actionable way to tell
them apart anyway.

**Range requests**: verified rather than assumed — the installed Starlette
version's `FileResponse` (1.3.1) parses `Range`/`If-Range` natively and
returns `206 Partial Content` with a correct `Content-Range` header
(`test_get_asset_file_supports_range_requests` asserts a real 10-byte range
request against the endpoint). No fallback/plain-full-file code path was
needed. This matters for `pdf.js`, which uses range requests for
progressive loading of large PDFs rather than fetching the whole file
upfront.

## ADR-020 — pdf2htmlEX: a Docker-gated post-ingest enhancement over the pdf.js view (2026-07-06)

Owner request: better-than-pdf.js rendering (real selectable text, no
client-side PDF.js worker cost per page) as an *optional* enhancement, not
a replacement for ADR-019's PDF-serving view. What this buys: pdf2htmlEX
produces real HTML+CSS per page — sharper at any zoom level than a
rasterized pdf.js canvas, and the text layer is genuinely selectable/
searchable rather than an invisible overlay approximating glyph
positions. The cost is a heavyweight native dependency (poppler + custom
patches, not pip/npm-installable) that this project has no interest in
building/maintaining directly — Docker isolates that entirely, at the
price of the feature simply not existing on a box without Docker. Hence
"auto" detection (`html_conversion_enabled()`, `smv2-dev-loop` §6) rather
than a hard dependency: the reader degrades to the ADR-019 pdf.js view
with zero code path difference, not an error state.

**No canonical Docker image exists** — worth recording since the original
task assumed one did. The pdf2htmlEX GitHub README never mentions Docker
at all; its own in-repo Dockerfile does an unpinned `git clone` of
`master` (not reproducible). Of the two pre-built Docker Hub candidates,
`bwits/pdf2htmlex:0.14.6` (the more-pulled one) fails to pull at all on a
modern Docker daemon — its manifest uses a format containerd 2.1+
rejects, verified by actually attempting the pull.
`pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-alpine-3.12.0-x86_64`
(~2020, x86_64-only, no arm64 build) is the one actually verified
pullable and runnable, so it's the default; `docker_image()` is
overridable via `SMV2_HTML_DOCKER_IMAGE` for a deployer's own better-
pinned build. Never bump the default to `:latest`.

**`--split-pages` does not produce standalone pages** — the second wrong
assumption in the original task, caught by actually running a real
conversion against the pulled image rather than trusting its `--help`
text alone. Split-page output (`page{N}.html`) is a bare content fragment
— no `<html>`/`<head>`/`<style>` wrapper, no `<link>` to any stylesheet —
meant to be injected into `index.html`'s own DOM by its bundled JS for
progressive loading in pdf2htmlEX's OWN multi-page viewer, not served
standalone. The actual layout/typography rules (page dimensions, font
metrics, positioning — everything a fragment needs to render correctly)
live in one small `shared.css` (`--css-filename shared.css --embed-css 0`);
the rest of the tool's default CSS (`base.min.css`/`fancy.min.css`) is
viewer-chrome (sidebar, loading spinner) for its own reader, irrelevant to
an independently-served page. `app.pipeline.html_conversion._wrap_page_fragment`
inlines `shared.css` into a real `<style>` tag around each fragment at
conversion time, producing the standalone file that's actually served —
this wrapping is not optional post-processing, it's required for the
served page to render at all.

**No script ever gets wrapped in**, which is why the CSP
(`default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src
data:`) omits `script-src` entirely rather than needing to explicitly
disable it: per-page fragments never contained a `<script>` tag to begin
with (JS lives only in `index.html`, never duplicated into split pages),
and the wrapper only ever adds `shared.css`, never JS — verified by
asserting `"<script" not in page1` in the test suite, not just assumed
from reading `--help`. This sidesteps a real upstream limitation: pdf2htmlEX's
own JS is load-bearing for font-rendering correctness in its normal mode
(disabling it is documented to break fonts), so if fragments *had* needed
JS, this CSP would have broken rendering — the fragments' actual structure
makes that a non-issue rather than something this design had to work
around.

**Why a post-ingest job, not part of ingest**: ingest must stay fast and
zero-LLM (ADR-010) regardless of whether this optional, Docker-dependent,
possibly-slow (spins up a container per asset) enhancement succeeds,
fails, or isn't even enabled. `run_ingest` enqueues `convert_html`
fire-and-forget, in the SAME commit as `course.status = "ready"`
(`session.add(Job(...))` before the final commit, no `jobs_service`
import needed — `Job` is already imported in `ingest.py`), only when
`any_extracted_ok and html_conversion_enabled()`. Per-asset isolation
mirrors ingest's own per-asset extraction isolation: one asset's
conversion failing sets only that asset's `html_status='failed'`, the job
continues to the next. A missing/failed image pull is a whole-job failure
(nothing to convert without the image at all) with a friendly,
Docker-mentioning error message, distinct from a per-asset conversion
failure. `Asset.html_status` is a user-visible status field the frontend
polls, so `convert_html` gets a custom orphan hook
(`_convert_html_on_orphan`, mirroring `_ingest_on_orphan`) rather than the
default: an exhausted retry flips any still-`'converting'` asset to
`'failed'` so the UI never shows a stale spinner.

**Test-isolation catch, the same class of bug as ADR-018's**: this
sandbox happens to have a real `docker` binary on PATH, so
`html_conversion_enabled()`'s `'auto'` default is `True` here unless
overridden — left alone, every successful `ingest_course` call in the
*entire pre-existing test suite* would have enqueued a real
`convert_html` job. That job sits queued and, being older, gets claimed by
the *next* `run_due_jobs_once()` call ahead of whatever job a test
actually intended (claim order is oldest-created-first) — silently
breaking any test that ingests more than once (three pre-existing
re-ingest tests went red the moment this was wired in, with no exception
thrown, just wrong content because the real re-ingest job never ran).
Fixed the same way as ADR-018's `ANTHROPIC_API_KEY` leak:
`tests/conftest.py::_setup_isolated_env` now forces
`SMV2_HTML_CONVERSION=0` for every test by default; the tests that
exercise this feature specifically override it back on. All Docker/
subprocess calls (`_docker_image_present`/`_docker_pull`/`_docker_convert`)
are separately mockable module-level functions specifically so the test
suite never shells out to a real `docker` binary at all.

**Manifest limitation, stated rather than silently accepted**: `{pages,
width_px, height_px}` is one dimension pair per asset, taken from the
PDF's first page via PyMuPDF (`page.rect.width/height`, matching
pdf2htmlEX's own default unscaled-to-points rendering — verified
numerically equal in a real conversion). A PDF with mixed page sizes
(e.g. one landscape page in an otherwise-portrait book) would have every
other page's actual dimensions misreported by this single pair. Not
handled — flagged here as a known gap rather than silently designed
around, since the spec asked for exactly this shape.

## ADR-021 — Drop ToC-shaped chapter cover pages from the outline (2026-07-06)

Owner-reported (live repro): a chapter's own cover page — "Chapter 1 :
Solving Linear Equations" (p.27), a mini table of contents listing that
chapter's own sections and their page numbers — was being ingested as a
1-page *content* section instead of being recognized as front matter for
that chapter. `app.pipeline.outline_detect.toc_shaped_chapter_cover_mask`
(gated by the existing `skip_front_matter()` flag) drops any section
where every page looks like a chapter-cover mini-ToC and the section
spans at most 3 pages (safety bound — shape alone never drops a long
section, only a short one is even eligible).

**Ordering is load-bearing, same class of bug as ADR-019's trigger-drop
catch**: the mask must be applied to `bounds_list` (and the identical mask
applied to `assign_chapter_labels`' output) *after* both have already
been computed against the full, undropped list. A cover section's own
title is exactly the `^chapter N` marker `assign_chapter_labels` anchors
on — dropping it first would silently orphan every section that chapter
marker was supposed to label. Labels are computed once and only ever
filtered alongside the mask afterward, never recomputed from the
shortened list; `ingest.py` and `scripts/make_fixtures.py::_snapshot_for`
both follow this same order.

**The spec's literal instruction ("reuse the same pure function the
leading-page skip uses," i.e. `_looks_like_toc_page`) would have shipped
a serious content-loss regression, caught only by the mandated real-book
verification step, not by unit tests written against the spec's own
premise.** Running the literal instruction against the real textbook
dropped 38 sections instead of the expected ~11 — the large majority were
real numbered practice worksheets ("1.1 Practice - One Step Equations":
"13) 9 = n - 5", "27) 20b = -200", ...), whose numbered problems mostly
end in a digit (the equation's own numeric answer/coefficient) for
exactly the same reason a genuine ToC line does, making them
indistinguishable under a bare "≥40% of lines end in a number" signal.
Fixed with a signal specific to this use case
(`_looks_like_chapter_cover_page`): require a dot leader ("....") between
the text and the trailing number — real ToC-style formatting has one, a
worksheet's numbered problem never does — and its own lower minimum line
count (3, not the shared `_TOC_LINE_MIN_COUNT=5`), since a legitimate
per-chapter mini-ToC can list as few as 3 sub-sections (the real
textbook's shortest genuine cover) where a book-level ToC would always
list many more. Re-verified against the same real book with the corrected
signal: 10 of 11 expected covers dropped (including both of the owner's
own cited examples, p.6 and p.27), zero practice sheets affected (kind
counts: `content` 94→84, `practice` unchanged at 76, `answers` unchanged
at 11), all 11 distinct chapter labels and every surviving section's
label unchanged. The one un-dropped cover ("Chapter 7 :
Rational Expressions") spans 4 pages — correctly kept by the explicit
3-page safety bound, not a miss.

`_EXTRACTOR_ALGO_VERSION` bumped `algo-6` → `algo-7`; `headings_no_bookmarks.pdf`
gained a 5th chapter whose own 1-page ToC-shaped cover ("Chapter 5:
Probability" + 5 dotted sub-section lines) is dropped from its snapshot
while the ordinary lesson section right after it ("5.1 Basic
Probability") still correctly inherits `chapter_label="Chapter 5:
Probability"` — proving the label-then-drop ordering in the golden
snapshot, not just in production code. No API/schema changes.

## ADR-022 — Learning-companion chat, deck/attempt split, performance-seeded SRS (2026-07-06)

Distilled from the owner's learn-anything skill family: chat becomes a
guided-discovery companion rather than a pure Q&A tool, tests become
reusable decks with a retake path, and answering a test question at all
(not just missing one) now feeds the SRS system. Five parts, one round.

**1. Per-file prompt resolution** (`app/llm/prompts.py::load_prompt`):
changed from "the one highest `vN` overall" to "the highest `vN` that
actually CONTAINS this file" — `prompts/v3/` holds only `chat.md`, so
`load_prompt("lesson"/"cards"/"quiz")` still resolves to `v2` exactly as
before, unaffected by chat's own version bump. This is the entire reason
per-file resolution replaced the old contract: a wholesale bump to `v3`
would have stale-flagged every existing lesson in every course the
moment this shipped, for a prompt change that never touched `lesson.md`
at all.

**2. Chat prompt v3** (`prompts/v3/chat.md`) — the learning-companion
persona: position the topic in the book's own outline, an analogy, the
core mechanism, a cited example from the excerpts, a misconception when
relevant, one closing Socratic check question. The check question is
explicitly non-gating ("ask it, then move on — give the answer
immediately if the learner seems unsure or asks directly"), matching the
owner's "guide, don't lecture" stance line. All v2 rules carry over
unchanged (excerpts-only grounding, `[n]` citations, LaTeX math,
untrusted-content tagging per ADR-005).

**3. Learner context injection** (`app/services/chat_service.py`,
`app/services/study_service.py`): every chat turn's user message can gain
two new tagged blocks alongside `<excerpts>`, both entirely
deterministic — the model never computes a statistic, only reads one:

- `<learner_state>`: one line per chapter the retrieval hit THIS TURN
  (never the whole course) — best/latest test score or "no test attempts
  yet", cards due/lapsed (via `Card`⟶`ReviewState` joins scoped to the
  chapter's content+practice sections), whether a lesson has been
  generated. Omitted entirely (not emitted empty) when retrieval hit no
  chaptered sections at all (e.g. a page-window-only course with no
  `^chapter N` markers).
- `<study_suggestions>`: the top-3 results of `study_service.study_next`,
  independent of what was asked this turn. Also exposed directly via `GET
  /api/courses/{id}/study-next` (`study_next`) for the dashboard.

`study_next`'s four-tier deterministic triage, each chapter suggested at
most once (by its highest-priority matching tier, skipped by every later
one): (a) failed/low best test score — worst first; (b) a due-card
backlog past a minimum count — heaviest first; (c) the course has never
been opened at all (`ProgressState` absent) — a single "start here" for
the first chapter, since `ProgressState` is course-scoped (one row, the
current position) and can't tell which *other* chapters were ever
visited; (d) stale — opened before, just not recently, weighted by
`(1 - score_norm) × days_since × weight` (an Anki-priority-style
formula), where an untested chapter's `score_norm` defaults to a neutral
0.5 rather than being treated as either mastered or failing. The exact
thresholds (`0.6` low-score cutoff, `5`-card minimum backlog, `1.0`
staleness weight) are this feature's own interpretive choices — the brief
didn't pin down numbers — documented in `study_service.py`'s own
docstring rather than guessed silently, same convention `srs_service.py`
already follows for its bootstrap-interval choices.

**4. Deck/attempt split** (migration `0007_test_deck_attempt_split`): new
`tests` table holds the generated deck (`questions`, `prompt_version`,
`model`, `chapter_label`, the single-section-mode `section_id`) —
generated once. `test_attempts` sheds its own `payload`/`chapter_label`/
`section_id`/`prompt_version` entirely, gains `test_id` (FK, CASCADE) and
now persists `answers`/`results` (previously computed at submit time and
returned but never written to the DB at all — a genuine gap this closes,
not just a rename). `POST /api/tests/{test_id}/attempts` (`retake_test`)
creates a new attempt against the SAME deck, zero further LLM calls;
`list_tests` is now test-grouped (one entry per deck with a nested,
newest-first attempt history) rather than a flat attempt list, matching
what a "retake" feature actually needs to display. Every existing
`test_attempts` row gets a backfilled `Test`, built from that row's own
`payload`/`chapter_label`/`section_id`/`prompt_version` (`model` is `None`
for backfilled rows — never tracked pre-split, nothing to recover).

**The hairy part, as flagged in advance**: SQLite/Alembic can't add a
`NOT NULL` column with no default to a table that already has rows (the
batch-mode rebuild's data copy would have nothing to put in the new
column for existing rows), so `test_id` is added nullable first, backfilled
row-by-row via lightweight `sa.Table()` Core declarations bound to the
migration's own connection (never the live ORM models — the standard
Alembic pattern, so a future model change can't silently break this
historical migration), *then* tightened to `NOT NULL` plus the FK
constraint in a second `batch_alter_table` pass. A second, independent
trap surfaced writing the `downgrade()`: an inline `sa.ForeignKey(...)`
on a column added via `batch_op.add_column` mid-batch has no name of its
own, and batch mode requires every constraint to be named — raises
`ValueError: Constraint must have a name` otherwise. Fixed the same way
ADR-019's migration did: the FK added as its own separately-named
`create_foreign_key` call. Verified with a real round-trip (upgrade with
a seeded legacy row → downgrade → re-upgrade) against a throwaway SQLite
file, not just read for plausibility.

**5. Performance-seeded cards on submit** (`tests_service.py`, extends
ADR-017's missed→SRS path): every question becomes a content-addressed
card now, not just missed ones — a correct answer on a **brand-new**
card seeds it as one successful review via the real
`schedule_next(GOOD, ...)` from the bootstrap state (first-Good baseline,
1 day, `reps=1`), so the whole tested deck enters spaced-repetition
rotation with the test as its first review event. A correct answer on an
**existing** card only advances it if the card was genuinely due or new
at that moment (`ReviewState.due_at <= now`) — a card not yet due is left
completely untouched. This is the cramming guard: without it, retaking a
test would let a learner farm schedule advancement on cards they only
just reviewed, by re-answering material whose next real review isn't due
yet. A miss keeps its pre-ADR-022 policy exactly (due now; ease/interval/
reps untouched on an existing card, no `ReviewState` at all needed for a
brand-new one).

`added_card_ids` in the submit response deliberately **keeps its
pre-ADR-022 meaning** — missed-question cards only — rather than
expanding to include every card touched: an existing frontend surface
already reads it as "cards that need your attention now," and a
correct-answer card seeded 1+ days out is not that. `due_now_count` is a
new, separate field counting the same set for this design (only a miss
ever produces a right-now-due outcome here) — genuinely redundant with
`len(added_card_ids)` in practice, called out explicitly in code rather
than left to look like an unexplained duplicate, since the spec asked for
both fields without fully disambiguating their relationship.

No `_EXTRACTOR_ALGO_VERSION` bump — nothing in extraction/outline changed
this round.

## ADR-023 — Card editing: content-addressing extended to user edits (2026-07-06)

Flashcards become visible and editable in the reader. The core design
question was how card editing coexists with `card_id_for`'s
content-addressed identity law (`smv2-invariants`, `smv2-srs-subsystem`
§1): a card's id is a hash of its own front/back text, so editing that
text necessarily produces a *different* id. Rather than special-casing
edits to mutate a row in place (which would break the id-matches-content
invariant every other part of the system relies on), an edit is modeled
as **mint a new card at the new id, migrate its review history onto that
id, delete the old row** — the same shape id stability already has
everywhere else, just applied to a manual edit instead of a
regeneration.

**1. `cards.origin` (migration `0008_card_origin`)**: plain
`op.add_column` with `server_default="generated"` — no FK, no trigger on
`cards` (only `sections` has one, scoped to `body_md`), so no
`batch_alter_table` needed, unlike ADR-019/ADR-022's FK-column additions.
`'generated'` (produced by `run_card_generation`) vs `'user'` (created by
an edit) is the flag every other part of this ADR keys off.

**2. `PATCH /api/cards/{card_id}` (`update_card`)**:
`cards_service.update_card` computes `new_id =
card_id_for(section_id, new_front, new_back)`. If `new_id == card_id`
(a byte-for-byte no-op edit — `card_id_for` does no text normalization,
unlike section identity's `normalize_text`), returns the existing card
unchanged. Otherwise: 404 if the card doesn't exist; 409
(`DuplicateCardError`) if `new_id` already belongs to a *different*
existing card in the section (the section's dedup law surfaced as a real
error rather than a silent merge) — insert the new `origin='user'` card
first (same `course_id`/`section_id`/`position`), then migrate
`ReviewState`/`ReviewLog` from the old id to the new one, then delete the
old card. That order matters: `PRAGMA foreign_keys=ON` enforces
`review_states.card_id`/`review_logs.card_id`'s FK per-statement, so the
new card must exist before either table is repointed at it, and the old
card must not be deleted until nothing still points at it.

**The PK-update question, resolved empirically**: `ReviewState.card_id`
is that table's own primary key, not just an FK column, so migrating it
meant either a raw `UPDATE review_states SET card_id = :new WHERE
card_id = :old` or a safer-seeming insert-copy-then-delete. Verified
directly against a throwaway SQLite file (mirroring ADR-022's
round-trip-verification habit): a plain SQLAlchemy Core `update()`
against the primary-key column works cleanly — the SQL-level UPDATE
succeeds once the new card row already exists (FK target present), and a
**fresh session** reading `session.get(ReviewState, new_id)` afterward
returns the row intact (`due_at`/`interval_days`/`reps` all preserved),
with the old id correctly returning `None`. No ORM identity-map
staleness observed. `ReviewLog.card_id` is a plain FK column (not a PK —
`ReviewLog` has its own `id`), so the same approach applies with even
less risk. `update_card` uses this raw-UPDATE approach for both tables;
the insert-copy+delete fallback was not needed.

**3. `DELETE /api/cards/{card_id}` (`delete_card`)**: deletes the row and
relies on `ON DELETE CASCADE` to remove its `ReviewState`/`ReviewLog` —
204 on success, 404 if missing. This is a **deliberately different**
outcome from an edit: deleting a card is permanent, intentional removal
of its review history along with it, whereas editing migrates that
history forward. Don't conflate the two code paths.

**4. Regeneration diff scoped to `origin='generated'`**
(`cards_generation.py`): the existing replace/remap diff (delete cards
absent from the new generated id set; update position for cards present
in both) now only ever considers `origin='generated'` cards as delete
candidates — a `origin='user'` card (freshly authored, or the result of
an edit) is invisible to the delete side of the diff entirely, mirroring
re-ingest's replace vs. remap split (`smv2-invariants` law #2/#3) for
content a person has deliberately customized. On the insert side, if a
newly generated card's content-addressed id happens to collide with an
existing `origin='user'` card's id, the insert is skipped and the user's
card (and its state) is left untouched — the user's card wins, not the
model's.

**Tests** (`tests/test_card_editing.py`,
`tests/test_cards_generation.py`): edit migrates `due_at`/`interval_days`
/`reps`/logs to the new id; no-op edit (identical content) returns the
same id, no new row; edit-to-duplicate-content → 409, both cards
untouched; delete cascades state+logs, verified by direct DB query after
a 204; `list_cards` includes `origin` for both kinds; a user-edited card
survives regeneration with completely unrelated new content; unedited
`origin='generated'` cards still replace exactly as before ADR-023; a
regeneration whose new content collides with an edited user card's id
skips the insert and preserves the user's card and its graded state.

No `_EXTRACTOR_ALGO_VERSION` bump — nothing in extraction/outline changed
this round.

## ADR-024 — Highlights are wiped on re-ingest; text-quote anchors (2026-07-17)

The `highlights` table (student highlights/notes: exact/prefix/suffix/
occurrence text-quote anchor + optional 0-based page + note_md) is
classified REPLACED_ON_REINGEST — re-uploading a course's PDF deletes its
highlights, and the upload UI must warn. Owner explicitly chose this over
remap-survival for the first build (spec:
docs/superpowers/specs/2026-07-17-highlights-notes-design.md); upgrading
to remap-survival later is additive. Anchors are text-quote based, not
CFI/DOM-position or char-offset based, because the same source text
renders in multiple DOMs (react-markdown, pdf.js text layer). The feature
is readest-inspired but uses zero readest code — readest's UI is AGPL-3.0
and must never be copied into this repo.

## ADR-025 — Positional margin notes: normalized-y anchor, separate Note table (2026-07-21)

The new `notes` table (student margin notes: `page` + `anchor_y` +
`note_md`, surface="pdf") lets a student annotate a spot on a PDF page
without selecting text. The anchor is `anchor_y`, a 0..1 top-origin
**fraction of the page height**, NOT pixels/CFI/text-quote: each PDF page
renders fit-to-width with a fixed aspect ratio, so a fraction tracks the
same spot when the page re-lays-out at any zoom/width, rendered as a plain
CSS `top: {anchor_y*100}%` inside the page's position:relative wrapper (no
JS geometry). A **separate** entity rather than overloading the text-quote
`Highlight` (whose `exact` is required and central); the NotesPanel is the
union of both. MVP scope: PDF surface only (a markdown source view reflows,
so a y-fraction is meaningless there), no colors/drag/cross-page notes.
Wiped on re-ingest like highlights (ADR-024) — classified
REPLACED_ON_REINGEST AND explicitly deleted in `_run_ingest`'s wipe block
(registry membership alone does not wipe; FK cascade doesn't fire for
sections kept unchanged across re-ingest). Spec:
docs/superpowers/specs/2026-07-21-margin-notes-design.md.

## ADR-026 — Outline confirmation reinstated in the new-course dialog; supersedes ADR-014 (2026-07-26)

The 2026-07-26 UI redesign (design handoff:
docs/design-frontend/Educational platform UI redesign/design_handoff_sourcemind_redesign/,
plan: docs/superpowers/plans/2026-07-26-ui-redesign.md) reintroduces the
outline-confirmation step that ADR-014 removed: the "Start a new course"
dialog now runs Upload → Confirm outline → Start reading, with the
detected outline shown as an explicit reviewable step (rename/split/merge,
staged with Undo) before the reader opens. This is an informed reversal,
not an oversight — the handoff README calls it out ("outline confirmation
returns as an explicit step... it currently lives only in the reader").
ADR-014's underlying observation ("verifying page numbers is not a user
job") is respected in the new UI: the step defaults to a one-click
"Accept outline & start reading" and never requires page-number editing;
Cancel simply dismisses (the course is already created and ingested, and
the outline stays editable from the reader's Edit outline modal, which
remains unchanged). ADR-014 is superseded on the upload-flow point only.
