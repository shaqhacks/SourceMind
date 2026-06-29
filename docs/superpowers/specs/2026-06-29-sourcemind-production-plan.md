# SourceMind — Production Plan

**Date:** 2026-06-29
**Status:** Roadmap (planning deliverable; not yet executed)
**Goal:** Take SourceMind from a single-user local tool to a production, multi-student SaaS where students upload textbooks and course materials, chat with an AI about them (NotebookLM-style, grounded and cited), review generated chapters/lessons, take graded tests on sections, and run spaced-repetition flashcards in the app.

This plan is the synthesis of three parallel analyses: a production-readiness audit, a NotebookLM-vs-RAG research brief, and a feature-completeness gap analysis.

---

## 1. The three findings that shape everything

1. **There is no concept of a user anywhere in the system.** No `user_id` on any table; every list/read/delete endpoint operates on all data globally (e.g. anyone can delete anyone's course). Multi-tenancy is the keystone — auth, quotas, isolation, per-user storage all hang off it. This is the single largest body of work and it gates the rest.

2. **NotebookLM has no usable API for what we need.** Google's NotebookLM Enterprise API (pre-GA, Sept 2025) manages notebooks and sources but does **not** expose grounded Q&A, is enterprise-license-gated (~$9/user/mo, Google Cloud org required), and the legacy `notebooklm_service.py` calls an undocumented endpoint (fragile, ToS-risky). **Wrapping NotebookLM is not a real option.** The replacement is a RAG pipeline we own, built on the stack we already run.

3. **Most "missing" features already exist as orphaned code.** SourceMind currently contains three overlapping backends; only the simplest (`/library`, DB-backed) is wired to the UI. Graded/scored test submission, grounded chat with citations, and multi-format ingest already exist in the other two (`/courses`, `/subjects`) but no UI reaches them. The biggest lever to "fully featured" is **consolidate + harvest**, not greenfield.

**Strategic consequence:** the order of work is (a) consolidate to one backend, (b) add tenancy/auth, (c) productionize infra, (d) harden cost + security, (e) build the RAG chat, (f) finish the learning features, (g) observability/CI/deploy — with legal/compliance running in parallel from day one.

---

## 2. Current state (what we are building from)

**Strengths (keep):**
- Clean generation pipeline: PDF extract (PyMuPDF) → outline (PDF bookmarks first, chunked-LLM fallback) → plan (objectives, importance, source-proportional word targets) → chapter generation → **validate→repair quality loop** (length band, worked examples, valid quiz, cards, grounding judge).
- Pluggable LLM provider (Claude default / local Ollama), hardened for local models (structured-output schema, thinking-model handling, truncation salvage).
- DB-backed `/library` flow with async ingest + status polling, an mdBook-style reader (inline images, embedded auto-graded quizzes), in-app SM-2 spaced repetition (all-subjects + per-subject), Anki TSV export, an in-app notifications bell, and course delete.
- ~291 backend tests; path-traversal and SSRF guards already written; explicit-origin CORS.

**Liabilities (resolve):**
- No tenancy/auth (keystone gap).
- Three coexisting backends (`/library` DB, `/courses` markdown, `/subjects`+`/lessons` markdown) with the frontend still referencing all of them — unsecured surface that must be consolidated before hardening.
- SQLite + in-process `BackgroundTasks` (non-durable jobs); local-filesystem assets; no cost controls; live upload path unhardened; no migrations, CI, Docker, or observability.
- Copyright exposure from hosting uploaded textbooks for a paid product; PII (`paystub_*.pdf`) and a real textbook committed in the tree.

---

## 3. Target architecture

```
Next.js (Vercel/host)  ──auth token──▶  FastAPI (web)  ──▶  Postgres + pgvector (managed)
        │                                   │   │  ▲                    ▲
        │                                   │   │  └── Redis ──┐        │
   browser SRS cache                        │   ▼             │        │
                                            │  Arq workers ◀──┘  (durable jobs:
                                            │   (ingest, generate, embed)        ingest/generate/embed)
                                            ▼
                                   Object storage (S3/GCS)  ── PDFs, extracted images, signed URLs
                                            │
              LLM: Claude (Anthropic) for generation + RAG answers, with per-user quota/metering + prompt caching
              Embeddings: Ollama nomic-embed-text (free, local) or hosted; vectors in pgvector
              Ingestion: Docling (PDF/DOCX/PPTX/HTML) + PyMuPDF fast path + youtube-transcript-api
```

**Chosen components (with rationale):**
- **Postgres + pgvector** — one database for relational data *and* RAG vectors; one backup story; `SOURCEMIND_DB_URL` already makes the swap trivial. Add **Alembic** for migrations.
- **Redis + Arq** for durable jobs — Arq is async-native and matches the FastAPI/asyncio codebase; the existing resume-from-`ready` logic is already idempotent. (Celery is the heavier alternative if richer tooling is wanted.)
- **S3/GCS + signed URLs** for PDFs and extracted images (replaces the local-FS asset proxy; the traversal guard can then be retired).
- **RAG**: Docling ingestion → chunk (300–500 tokens, ~15–20% overlap, split on headings) → embed with Ollama `nomic-embed-text` (768-dim, free) → store in pgvector with `source_ref` metadata (HNSW index, optional hybrid full-text) → retrieve top-k → Claude answers with citations. Optional re-ranker later.
- **Auth**: JWT (stateless, mobile-friendly later) or server sessions; a `current_user` dependency that filters every query and authorizes every endpoint.

---

## 4. Phased roadmap

Each phase lists the objective, key tasks, and acceptance. Phases are mostly sequential because tenancy gates everything, but several can overlap (noted).

### Phase 0 — Consolidate to one backend *(blocker, ~1 week)*
You cannot secure three parallel systems; collapse to one first.
- Choose `/library` (DB system) as the home.
- Migrate any still-needed UI off `/courses`, `/subjects`/`/lessons`, `/upload`.
- **Harvest before deleting**: lift the genuinely useful logic out of the legacy code into `/library` + the DB model — specifically the **graded quiz-submit** (scored/pass-fail), **grounded chat with `source_refs`/citations**, and **multi-format ingest** (text/markdown/URL/YouTube).
- Delete the legacy routers, markdown stores, and orphaned frontend pages; remove the dual `api`/`library` clients.
- Remove the committed textbook and `paystub_*.pdf` from the tree/history.
- **Acceptance:** one backend surface; `git grep` shows no frontend references to legacy routes; tests green.

### Phase 1 — Multi-tenancy & auth *(keystone blocker, 2–4 weeks)*
- `User`/`Account` table; signup + login; JWT or sessions; password (or OAuth — Google is natural for students).
- Add `user_id` FK to every owned row (Course, Chapter, Asset, PlanItem, ProgressState, ReviewState, ChatTurn, and the new RAG chunks).
- A `current_user` dependency; **every** query filtered by user; **every** endpoint authorized. Per-user slug namespacing (course_id is currently a global slug).
- Frontend: login/signup, token storage, authed fetch wrapper, route guards.
- **Acceptance:** a user can only see/modify their own data; an authz test suite proves cross-user access is denied on every endpoint.

### Phase 2 — Production infrastructure *(blocker, 1–2 weeks; can overlap Phase 1)*
- Managed **Postgres**; **Alembic** migrations (replace `create_all`); pooling (`pool_pre_ping`, sizes); indexes on `user_id`/`course_id`.
- **Redis + Arq**; port `run_ingest_job` and `generate_course` to durable tasks with retry/backoff, concurrency caps, and cross-process progress; workers scale separately from web.
- **S3/GCS** for PDFs, extracted images, `pages.json`; signed URLs.
- **Acceptance:** a deploy/restart mid-generation resumes cleanly; assets survive redeploy; migrations run in CI.

### Phase 3 — Cost control & security hardening *(blocker, ~1 week; overlaps Phase 1/2)*
- **Move upload hardening to the live `/library/uploads`** path (size cap, MIME + `%PDF-` magic-byte check, streamed write instead of `await upload.read()` into memory). The validation already exists in the legacy `/upload` router — port it.
- **Sanitize PDF text and `body_md` before every LLM call** (prompt-injection); the sanitizer (`ingest/security.py`) is currently wired only for URL/YouTube. Wire `validate_public_url` (SSRF) before any fetch.
- **LLM cost controls:** token metering + per-user quota/credits + hard spend cap; Anthropic **prompt caching** for repeated source text (large cut on multi-section generation); provider-level **timeouts + retry** (a hung call currently blocks a worker forever); per-user concurrency limit.
- Per-IP/user rate limits.
- **Acceptance:** a single user cannot run up unbounded spend or DoS the worker; malicious upload/prompt-injection inputs are rejected/neutralized.

### Phase 4 — RAG chat (the marquee "NotebookLM" feature) *(2–4 days core, more for polish)*
- Add a `chunks` table in pgvector (`source_id`, `source_ref`, `content`, `embedding vector(768)`, metadata; HNSW index).
- Ingestion path embeds each material's chunks at upload time (Arq job).
- **Course-level (cross-material) chat**: embed the question → retrieve top-k across all of a course's materials → Claude answers **with citations** (`source_ref` returned to the UI) → persist and **reload** `ChatTurn` history (today it's written but never read back).
- Stream responses (SSE) for the NotebookLM feel.
- Optional: hybrid (vector + full-text) retrieval; a re-ranker.
- **Acceptance:** a student asks a question about their uploaded book and gets a grounded answer citing specific pages/sections; conversation persists across refresh.

### Phase 5 — Finish the learning features *(harvest-led, ~1–2 weeks)*
- **Tests on sections (d):** wire the existing scored quiz-submit into `/library` + DB; add a distinct test mode (per-section and per-course, scored, pass/fail, attempt history, optional timer) with a results screen.
- **Multi-format upload (a):** expose the existing text/markdown/URL/YouTube ingest in the upload UI and route it through the DB pipeline; add **Docling** for DOCX/PPTX and layout-rich/scanned PDFs (one ingestion gateway; keep PyMuPDF as the fast path); `youtube-transcript-api` for videos.
- **SRS depth (e):** stats/streaks/daily goal, per-card mastery view, 4-button grading (again/hard/good/easy) instead of binary, fix the silently-advancing grade-error.
- **Reader polish (c):** reading-time/progress %, TOC search/filter, LaTeX/math rendering, code highlighting, mobile-scrollable tables.
- **Acceptance:** all five intended features are reachable, persistent, and usable on mobile.

### Phase 6 — Observability, CI/CD, deploy *(important, ~1 week)*
- Sentry (backend + frontend); structured JSON logs with request + user IDs; a real readiness probe (DB/Redis/LLM); metrics (generation latency, LLM cost, queue depth); a consistent client error envelope (frontend currently swallows most errors).
- GitHub Actions (lint + pytest + frontend build + migration check); Dockerfiles + compose; one deploy target (Fly/Render/ECS); a minimal Playwright e2e (there are zero frontend tests today).
- **Acceptance:** push-to-deploy with tests gating; errors are visible to operators; health reflects real dependencies.

### Phase 7 — Legal & compliance *(blocker, runs in parallel from day 1)*
- Counsel review of **copyright/DMCA/fair-use** for hosting and generating derivative content from uploaded textbooks (this is a business-gating risk, not an end-of-project task). Consider positioning (user-owned uploads, DMCA takedown process, no redistribution).
- ToS / Acceptable Use Policy; per-user **data export and hard delete**; retention policy; consent capture; PII minimization; DPA if serving EU students.
- **Acceptance:** ToS/AUP live; "delete my data" works end to end; a copyright posture is documented and signed off.

---

## 5. Decisions for the owner (with recommendations)

| Decision | Recommendation | Why |
|---|---|---|
| NotebookLM wrapper vs build RAG | **Build RAG** | No grounded-Q&A API exists; RAG is ~2–4 days on the current stack and we control citations/quality. |
| Consolidate vs keep 3 backends | **Consolidate to `/library`, harvest then delete** | Removes ~1.2k LOC of unsecured surface; halves the auth/quota work. |
| Auth model | **JWT** (or Google OAuth for students) | Stateless, scales horizontally, easy mobile later; sessions are the simpler-revocation alternative. |
| Job queue | **Arq + Redis** | Async-native fit; existing resume logic is already idempotent. |
| Vector store | **pgvector** | One DB, one backup, SQL joins to course/user tables; no new infra. |
| Embeddings | **Ollama `nomic-embed-text`** | Free, local, no egress; upgrade to `qwen3-embedding` later if needed. |
| Cost model | **Per-user credits/quota + hard cap + prompt caching** | Prevents financial DoS; protects margins. |
| Hosting | Managed Postgres + a container host (Fly/Render) + S3/GCS | Standard, low-ops. |
| Monetization (business) | Out of scope here, but the quota model should map to a pricing tier | Quotas are both a cost control and a paywall lever. |

---

## 6. Top blockers before any paying user

1. Auth + per-user isolation (today anyone can read/delete anyone's data).
2. LLM spend caps / per-user quota (generation is uncapped — financial DoS risk).
3. Harden the live upload path (`/library/uploads` has no size/MIME/magic-byte check; memory-buffered read).
4. Durable job queue (`BackgroundTasks` die on restart, stranding courses in `generating`).
5. Postgres + migrations (SQLite + concurrent multi-user writes will lock; no migration path).
6. Copyright/ToS + data-deletion (legal exposure; no account = no "delete my data").
7. Prompt-injection sanitization on the PDF/chat path (uploaded text reaches the LLM unsanitized).
8. Provider-level timeouts + retry, and consolidate/remove the two legacy backends so security covers the whole surface.

---

## 7. Rough sequencing & effort

- **Foundational (must precede paying users):** Phase 0 (1w) → Phase 1 (2–4w) with Phase 2 (1–2w) and Phase 3 (1w) overlapping → ~6–8 weeks of focused work, plus Phase 7 legal running alongside.
- **Marquee feature:** Phase 4 RAG chat (~2–4 days core) can start once Phase 1 tenancy lands (chunks need `user_id`).
- **Feature completion & polish:** Phase 5 (1–2w), Phase 6 (1w).
- Total to a credible paid beta: roughly **8–12 weeks** of focused engineering, gated by the legal review.

This roadmap is intentionally ordered so that the first move (consolidate) shrinks the second move (tenancy), and the highest-value user-facing feature (cited chat) is unblocked as soon as the tenant model exists.
