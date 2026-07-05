# SourceMind Architecture

Last substantially revised: 2026-07-05 (zero-LLM ingest, ADR-010). Companion docs: repo-root `CLAUDE.md` (working agreements), `docs/decisions.md` (why-records).

## System map

```
frontend/  Next.js App Router (plain JS, all-client today)
  app/lib/api.js         — single fetch boundary to the backend
  app/lib/usePolling.js  — the one polling primitive
  app/components/        — Chat (shared chat widget), GradedTest, Notifications, ...

backend/   FastAPI
  main.py                — app wiring: lifespan runs init_db() then reconcile_interrupted_jobs()
  config.py              — lazy env accessors (the ONLY place env is read)
  routers/library.py     — thin HTTP layer: validate existence, delegate, shape responses
  extract/
    pdf.py               — PDF → ExtractedPage: layout-aware Markdown via pymupdf4llm
                            (headings/paragraphs/lists, ADR-011), falls back to plain text
    material.py           — unified extraction for docx/pptx/txt/md/url/youtube/text
  pipeline/
    service.py           — ingest + generation + study orchestration (course lifecycle)
    chat.py              — tutor/course chat: prompt build, retrieval, ChatTurn persistence
    outline.py / plan.py — outline (bookmark-first, deterministic page-window fallback) + plan metadata (ADR-010)
    chapter.py           — chapter generation prompt + parse
    template.py          — Path-to-Staff template, quiz/card parsing, word counting
    validate.py          — deterministic checks + LLM grounding + bounded repair loop
    chunk.py             — section-aware chunking for RAG
    retrieve.py          — numpy cosine ranking (pure-python fallback)
  services/grading.py    — quiz + course-test grading (pure functions)
  llm/
    provider.py          — provider selection (claude | ollama)
    claude.py, ollama.py — providers; client constructed once, reused
    limiter.py           — llm_slot(): the global LLM/embed concurrency gate
    _timeout.py          — timeout + transient-only retry with backoff
    embed.py             — batched Ollama embeddings
  db/
    base.py              — engine cache, get_session, init_db (create_all/stamp/upgrade logic)
    models.py            — ORM
    migrations/          — Alembic (env.py resolves SOURCEMIND_DB_URL)
```

## Course lifecycle

1. **Upload/ingest** (`ingest_pdfs` → `_finish_ingest`): extract pages (layout-aware Markdown via pymupdf4llm — real headings/paragraphs/lists, falls back to plain text on any failure; ADR-011) + images, **zero-LLM outline** (ADR-010) — bookmark-first (`sections_from_toc`, picks the deepest bookmark level yielding 4-80 chapters) falling back to fixed page-range windows (`sections_from_page_windows`, `SOURCEMIND_FALLBACK_PAGES_PER_CHAPTER`, default 15) titled "Pages A-B" when a source has no usable embedded TOC — then persist Course/PlanItem/Chapter/Asset with deterministic plan defaults (`default_plan`: objectives=[], importance="supporting", `target_words` from real source word counts). Title/copyright/dedication/printed-TOC pages are carved into their own real, readable "Front Matter" chapter (`carve_front_matter`) rather than folded into chapter 1 — the boundary comes from the bookmark outline's own first chapter when one exists, otherwise from a deterministic keyword/dot-leader-line heuristic (`detect_front_matter_pages`) scoped to the leading pages only. Chapters are immediately readable: `body_md` = raw source markdown for the section's page range. Re-ingest of the same course_id wipes ALL derived rows first (see invariant #2 in CLAUDE.md).
2. **Index** (`index_course`): section-aware chunks (never straddle chapters, `source_ref = "{section_id}:p.N"`), batched embeddings, delete-then-insert Chunk rows.
3. **Lazy per-chapter refinement** (ADR-010): the first `ensure_study`/`generate_lesson` call for a chapter also runs `ensure_plan_metadata` — one bounded LLM call scoped to that chapter's own source text fills real objectives/importance (recomputing `target_words` for the learned importance); cross-chapter `prerequisites` stay `[]` (need whole-outline context this call deliberately doesn't have). Separately, the `get_chapter`/`study` routers opportunistically kick off `maybe_refine_title`/`run_title_refinement_job` as a background task the first time a page-window chapter (`Chapter.title_status="placeholder"`) is read, replacing its "Pages A-B" title with a real one without blocking the read.
4. **Generate** (background): `generate_course` iterates sections calling `generate_lesson`; skips sections already `lesson_status="ready"` (resumable by design). `regenerate_section` = `generate_lesson(force=True)`. Generated content goes ONLY to `lesson_md`.
5. **Study/review**: study items + ReviewState seeded per card (`_seed_review_states`), SM-2-style scheduling, due-ordering compares ISO-8601 strings (`due_at` seeded with real UTC timestamps).
6. **Chat**: retrieve top chunks (one query embedding per request), cite `source_ref`, persist ChatTurn rows.

## Data contracts

| Column | Contract |
|---|---|
| `Chapter.body_md` | immutable extracted source text |
| `Chapter.lesson_md` / `lesson_status` | generated lesson; `none → generating → ready \| failed` |
| `Chapter.title_status` | ADR-010 lazy title refinement; `None`/`"toc"` (authoritative) or `"placeholder" → refining → refined \| failed` |
| `Course.status` | `ingesting → ready \| ingest_failed` (+ `failed` set by reconciler) |
| `Course.generation_status` | `idle → running → succeeded \| failed` |
| `Chunk.source_ref` | display-only string; frontend never parses it |
| `Course.created_at/updated_at` | DB-managed DateTime (server_default/onupdate) — don't set in code |

## Failure model

- **Process restart**: BackgroundTasks are lost. `reconcile_interrupted_jobs()` (lifespan) fails-over anything stuck in `ingesting`/`running`/`generating`/title-`refining`. Generation is re-runnable manually because `generate_course` skips ready sections; a stuck title refinement is retried automatically on the chapter's next read (`"failed"` is a retryable state, not terminal). There is no automatic resume (debt item #1).
- **LLM errors**: transient (timeout/conn/5xx) retried once with backoff+jitter; 4xx raise immediately. Unparseable structured output gets ONE re-ask, then graceful degradation (empty quiz / default plan) — `validate.py`'s repair loop is the backstop for quality, and it skips re-running the grounding LLM call once grounding has passed.
- **Concurrency**: one global `llm_slot()` bounded semaphore inside providers/embeds. Saturation blocks callers (no 429 fast-fail — deliberate tradeoff, see decisions.md).

## Testing model

Temp SQLite per test via monkeypatched `SOURCEMIND_DB_URL` (why config must stay lazy). All LLM/network stubbed. TestClient runs BackgroundTasks synchronously — good for asserting outcomes, blind to in-flight states.
