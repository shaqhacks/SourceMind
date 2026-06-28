# SourceMind Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SourceMind's fragmented micro-competency lesson generator with a source-grounded pipeline that produces verbose, Path-to-Staff-quality chapters, backed by a SQLite DB and a pluggable LLM provider.

**Architecture:** Build a clean new backend module set (`backend/db`, `backend/llm`, `backend/extract`, `backend/pipeline`, `backend/routers/library.py`) alongside the legacy code. Generation flow: PDF → extract text+images (PyMuPDF) → outline → plan (user-approved) → per-section chapter generation with a validate→repair loop → persist Chapter rows. The Next.js frontend is reworked into an mdBook-like reader. Legacy `course_engine`/`md_store` paths stay until the new path is wired, then are retired.

**Tech Stack:** FastAPI, SQLAlchemy 2.x + SQLite, PyMuPDF (fitz), Anthropic SDK (Claude) / Ollama, Pydantic v2, Next.js 15 / React 19.

## Global Constraints

- Python import root is the repo's parent dir; package path is `SourceMind.backend.*`. `pytest.ini` sets `pythonpath = ..`.
- Run backend tests with: `uv run pytest backend/tests` from repo root.
- New deps must be added to `backend/requirements.txt` AND `scripts/build.sh`'s `UV_DEPS` array if it pins deps.
- Single-user local: NO auth, NO user_id columns.
- DB default = SQLite file at `data/sourcemind.db` (env `SOURCEMIND_DB_URL` overrides).
- LLM provider chosen by env `SOURCEMIND_LLM_PROVIDER` (`claude` default, `ollama` fallback); model by `SOURCEMIND_LLM_MODEL`.
- Markdown body conventions (must be identical across generator, renderer, Anki builder): quiz = fenced ```` ```quiz ```` block of JSON `{q, options[], answer, explain}`; try-it = `> ✏️ Try it:` blockquote + optional `<details>`; cards = `## Spaced-Repetition Cards` heading then `- **Q:** … **A:** …` bullets; images = `![caption](<url>)`.
- Word-count targets are per-chapter computed (source-proportional), never a fixed global band.
- Cards required only for `importance == "core"` sections.
- Every backend task is TDD: failing test → run → implement → run → commit.

---

## Phase 1 — Foundation: DB + LLM provider

### Task 1: SQLAlchemy engine, session, Base

**Files:**
- Create: `backend/db/__init__.py`
- Create: `backend/db/base.py`
- Test: `backend/tests/test_db_base.py`

**Interfaces:**
- Produces: `engine`, `SessionLocal`, `Base`, `get_session()` (contextmanager yielding a `Session`), `init_db()` (creates all tables), `db_url()` (reads `SOURCEMIND_DB_URL`, default `sqlite:///data/sourcemind.db`).

- [ ] **Step 1: Failing test**
```python
# backend/tests/test_db_base.py
import os
from SourceMind.backend.db import base

def test_init_db_creates_sqlite(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_file}")
    eng = base.make_engine()
    assert eng.url.database.endswith("t.db")

def test_get_session_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    base.init_db(base.make_engine())
    with base.get_session() as s:
        assert s.execute(__import__("sqlalchemy").text("select 1")).scalar() == 1
```
- [ ] **Step 2: Run** `uv run pytest backend/tests/test_db_base.py -v` → FAIL (module missing)
- [ ] **Step 3: Implement** `backend/db/base.py`: `DeclarativeBase` subclass `Base`; `db_url()` reads env with default; `make_engine(url=None)` → `create_engine(url, connect_args={"check_same_thread": False})` for sqlite; module-level `engine` + `SessionLocal = sessionmaker(...)`; `get_session()` contextmanager commit/rollback/close; `init_db(engine)` → `Base.metadata.create_all(engine)`. Ensure `data/` dir is created if sqlite path.
- [ ] **Step 4: Run** the test → PASS
- [ ] **Step 5: Commit** `feat(db): add SQLAlchemy engine/session/base`

### Task 2: ORM models

**Files:**
- Create: `backend/db/models.py`
- Test: `backend/tests/test_db_models.py`

**Interfaces:**
- Consumes: `Base` from Task 1.
- Produces ORM classes: `Course`, `PlanItem`, `Chapter`, `Asset`, `ProgressState`, `ReviewState`, `ChatTurn`. JSON-typed columns use `sqlalchemy.JSON`.

Schema (columns):
- `Course(id PK str, title, status, generation_status, generation_progress JSON, generation_last_error, created_at, updated_at)`
- `PlanItem(id PK int, course_id FK, section_id str, title, objectives JSON, importance str, prerequisites JSON, target_words int, order int)`
- `Chapter(id PK int, course_id FK, section_id str, title, objectives JSON, importance str, source_pages JSON, assets JSON, body_md TEXT, quiz JSON, cards JSON, word_count int, status str)`
- `Asset(id PK str, course_id FK, path str, source_page int, caption str)`
- `ProgressState(id PK int, course_id FK, section_id str, completed bool, last_viewed_at)`
- `ReviewState(id PK int, course_id FK, section_id str, card_index int, ease float, interval int, due_at str, reps int)`
- `ChatTurn(id PK int, course_id FK, section_id str, role str, content TEXT, created_at)`

- [ ] **Step 1: Failing test** — create a `Course` + `Chapter`, commit, query back; assert `chapter.quiz` round-trips a list of dicts.
```python
def test_course_chapter_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    from SourceMind.backend.db import base, models
    base.init_db(base.make_engine())
    with base.get_session() as s:
        s.add(models.Course(id="algebra", title="Algebra", status="ready"))
        s.add(models.Chapter(course_id="algebra", section_id="1-2", title="Integers",
                             body_md="# x", quiz=[{"q":"?","options":["a"],"answer":0,"explain":"e"}],
                             cards=[], objectives=["o"], importance="core",
                             source_pages=[1,2], assets=[], word_count=3, status="ready"))
    with base.get_session() as s:
        ch = s.query(models.Chapter).filter_by(course_id="algebra").one()
        assert ch.quiz[0]["answer"] == 0
```
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** models per schema above.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(db): add ORM models for course/chapter/plan/srs`

### Task 3: LLM provider abstraction

**Files:**
- Create: `backend/llm/__init__.py`, `backend/llm/provider.py`, `backend/llm/claude.py`, `backend/llm/ollama.py`
- Test: `backend/tests/test_llm_provider.py`
- Modify: `backend/requirements.txt` (add `anthropic>=0.40.0`, `SQLAlchemy>=2.0.0`, `pymupdf>=1.24.0`)

**Interfaces:**
- Produces:
  - `class LLMProvider(Protocol): def complete(self, prompt: str, *, system: str = "", schema: dict | None = None, max_tokens: int = 4096) -> str | dict`
  - `ClaudeProvider(model: str)`, `OllamaProvider(model: str)`
  - `get_provider() -> LLMProvider` (factory from env `SOURCEMIND_LLM_PROVIDER` / `SOURCEMIND_LLM_MODEL`).
  - When `schema` is given, provider returns a `dict` validated against the JSON schema (Claude via tool-use forced call; Ollama via `format=json` + parse).

- [ ] **Step 1: Failing test** — inject a fake provider; assert factory returns Ollama when env set; assert `complete(schema=...)` returns dict for a stubbed transport.
```python
def test_factory_selects_ollama(monkeypatch):
    monkeypatch.setenv("SOURCEMIND_LLM_PROVIDER", "ollama")
    from SourceMind.backend.llm import provider
    p = provider.get_provider()
    assert p.__class__.__name__ == "OllamaProvider"
```
For the transport, patch `anthropic.Anthropic` / `ollama.chat` so no network. Assert a `complete()` call with a schema returns a parsed dict.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement.** `provider.py`: Protocol + `get_provider()`. `claude.py`: wrap `anthropic.Anthropic`; for `schema`, pass a single tool with `input_schema=schema`, `tool_choice={"type":"tool","name":...}`, return `tool_use.input`. For plain text, return the text block. `ollama.py`: wrap `ollama.chat`; for schema pass `format="json"` then `json.loads`. Confirm exact Anthropic model id and message API against the `claude-api` reference skill before hardcoding — default model string lives in one constant.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(llm): add pluggable LLM provider (claude default, ollama fallback)`

---

## Phase 2 — Ingestion: PDF text + images

### Task 4: PyMuPDF extraction

**Files:**
- Create: `backend/extract/__init__.py`, `backend/extract/pdf.py`
- Test: `backend/tests/test_extract_pdf.py`

**Interfaces:**
- Produces:
  - `@dataclass ExtractedPage{ page_number:int, text:str, image_paths:list[str] }`
  - `extract_pdf(pdf_path: Path, assets_dir: Path) -> list[ExtractedPage]` — per page: `page.get_text("text")`; extract embedded images via `page.get_images()` → save PNG to `assets_dir`, record path + page. Also render figure-region crops is optional/v2 — for v1 just embedded images.

- [ ] **Step 1: Failing test** — generate a tiny 1-page PDF with PyMuPDF in the test (insert text + a small image), run `extract_pdf`, assert text contains the inserted string and at least one image path exists on disk.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** `extract_pdf` using `fitz`.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `feat(extract): PyMuPDF text+image extraction`

---

## Phase 3 — Outline + Plan

### Task 5: Outline detection

**Files:**
- Create: `backend/pipeline/__init__.py`, `backend/pipeline/outline.py`
- Test: `backend/tests/test_pipeline_outline.py`

**Interfaces:**
- Consumes: `LLMProvider`, `ExtractedPage`.
- Produces: `@dataclass Section{ section_id:str, title:str, page_start:int, page_end:int }`; `detect_outline(pages, provider) -> list[Section]`. Uses provider with a JSON schema (list of `{section_id,title,page_start,page_end}`). Cap sections (env, default 120).

- [ ] **Step 1: Failing test** — stub provider returning a fixed JSON outline for 3 fake pages; assert parsed into `Section` objects with correct ids.
- [ ] **Step 2–4:** run-fail → implement → run-pass.
- [ ] **Step 5: Commit** `feat(pipeline): outline detection`

### Task 6: Plan generation

**Files:**
- Create: `backend/pipeline/plan.py`
- Test: `backend/tests/test_pipeline_plan.py`

**Interfaces:**
- Consumes: `Section`, `ExtractedPage`, `LLMProvider`.
- Produces: `@dataclass PlanItem{ section_id, title, objectives:list[str], importance:str, prerequisites:list[str], target_words:int }`; `generate_plan(sections, pages, provider) -> list[PlanItem]`; helper `compute_target_words(source_words:int, importance:str) -> int` (pure, deterministic).
- `compute_target_words`: `base = source_words * expansion`; `expansion` = 1.6 core / 1.2 supporting / 0.8 peripheral; clamp to `[400, 3000]`.

- [ ] **Step 1: Failing test** — unit-test `compute_target_words(1000, "core") == clamp(1600,...)==1600`; and `generate_plan` with stubbed provider yields importance + objectives.
- [ ] **Step 2–4:** run-fail → implement → run-pass.
- [ ] **Step 5: Commit** `feat(pipeline): plan generation with source-proportional targets`

---

## Phase 4 — Chapter generation + validate/repair (the core)

### Task 7: Template + body parsing

**Files:**
- Create: `backend/pipeline/template.py`
- Test: `backend/tests/test_pipeline_template.py`

**Interfaces:**
- Produces:
  - `PATH_TO_STAFF_TEMPLATE: str` (the system/template prompt describing the 9-part chapter shape from the spec).
  - `parse_quiz(body_md:str) -> list[dict]` — extracts all ```` ```quiz ```` JSON blocks.
  - `parse_cards(body_md:str) -> list[dict]` — extracts `**Q:** … **A:** …` bullets under `## Spaced-Repetition Cards`.
  - `count_words(body_md:str) -> int` (strips code/quiz blocks).
  - `count_worked_examples(body_md:str) -> int` (counts `### Worked Example` or worked-example markers — define the marker the template emits and match it).

- [ ] **Step 1: Failing test** — feed a hand-written sample chapter markdown (in the test) through `parse_quiz`/`parse_cards`/`count_words`; assert counts.
- [ ] **Step 2–4:** run-fail → implement → run-pass.
- [ ] **Step 5: Commit** `feat(pipeline): chapter template + body parsers`

### Task 8: Chapter generation

**Files:**
- Create: `backend/pipeline/chapter.py`
- Test: `backend/tests/test_pipeline_chapter.py`

**Interfaces:**
- Consumes: `PlanItem`, `ExtractedPage` slice, `LLMProvider`, `PATH_TO_STAFF_TEMPLATE`.
- Produces: `@dataclass ChapterDraft{ section_id, title, body_md, quiz, cards, word_count }`; `generate_chapter(plan_item, source_text, image_urls, provider) -> ChapterDraft`. Builds the prompt: template + objectives + importance + target_words + the real source text + available image URLs (instruct inline placement). Parses quiz/cards out of returned body via Task 7.

- [ ] **Step 1: Failing test** — stub provider returns a full sample chapter; assert draft has parsed quiz/cards and `word_count>0`.
- [ ] **Step 2–4:** run-fail → implement → run-pass.
- [ ] **Step 5: Commit** `feat(pipeline): source-grounded chapter generation`

### Task 9: Validation + repair loop

**Files:**
- Create: `backend/pipeline/validate.py`
- Test: `backend/tests/test_pipeline_validate.py`

**Interfaces:**
- Consumes: `ChapterDraft`, `PlanItem`, `LLMProvider` (for grounding judge).
- Produces:
  - `@dataclass Issue{ code:str, detail:str }`; `@dataclass Report{ ok:bool, issues:list[Issue] }`.
  - `validate(draft, plan_item, source_text, provider, *, had_figures:bool) -> Report` — checks: word count within ±25% of `target_words`; `count_worked_examples>=2`; `len(quiz) in 1..; each item has explain`; if `importance=="core"` then `len(cards)>=1`; if `had_figures` then ≥1 image ref in body; grounding judge call → unsupported claims fail.
  - `generate_validated(plan_item, source_text, image_urls, provider, *, max_rounds=2) -> ChapterDraft` — generate, validate, and on failure call `provider` with a targeted repair prompt listing `issues`, re-validate, up to `max_rounds`.

- [ ] **Step 1: Failing tests** — (a) draft with 0 worked examples → `Report.ok is False` with code `worked_examples`; (b) core importance with no cards → fails; (c) grounding judge stubbed to "unsupported" → fails. Stub provider so the grounding-judge call is deterministic.
- [ ] **Step 2–4:** run-fail → implement → run-pass.
- [ ] **Step 5: Commit** `feat(pipeline): validate→repair quality loop`

### Task 10: Course service (orchestration + persistence)

**Files:**
- Create: `backend/pipeline/service.py`
- Test: `backend/tests/test_pipeline_service.py`

**Interfaces:**
- Consumes: all of Phase 1–4, DB models.
- Produces:
  - `ingest_pdfs(course_id, title, pdf_paths) -> None` — extract, persist Course(status=`needs_review`) + Assets, run outline+plan, persist PlanItems.
  - `approve_plan(course_id) -> None` — set status `generating`.
  - `generate_course(course_id, provider=None) -> None` — for each PlanItem in prereq/order, `generate_validated`, persist Chapter, bump `generation_progress`. Idempotent/resumable (skip sections already `ready`).
  - `regenerate_section(course_id, section_id) -> None`.

- [ ] **Step 1: Failing test** — with a stubbed provider (deterministic outline/plan/chapter), run `ingest_pdfs` on a tiny generated PDF then `generate_course`; assert N Chapter rows persisted with `status=='ready'` and progress complete.
- [ ] **Step 2–4:** run-fail → implement → run-pass.
- [ ] **Step 5: Commit** `feat(pipeline): course orchestration service`

---

## Phase 5 — API layer

### Task 11: Library router (DB-backed)

**Files:**
- Create: `backend/routers/library.py`
- Modify: `backend/main.py` (include router)
- Create: `backend/services/anki_export.py`
- Test: `backend/tests/test_router_library.py` (FastAPI `TestClient`)

**Interfaces (endpoints):**
- `POST /library/uploads` (multipart PDFs) → ingest → `{course_id}`
- `GET /library/courses` → list (id, title, status, progress)
- `GET /library/courses/{id}` → course + plan + chapter list (ids/titles/status)
- `GET /library/courses/{id}/plan` ; `POST /library/courses/{id}/plan/approve`
- `POST /library/courses/{id}/generate` (background task → `generate_course`)
- `GET /library/courses/{id}/chapters/{section_id}` → full chapter (body_md, quiz, cards, assets)
- `POST /library/courses/{id}/chapters/{section_id}/progress` `{completed}`
- `POST /library/courses/{id}/chapters/{section_id}/chat` `{question}` → grounded reply via provider; persist ChatTurn
- `GET /library/courses/{id}/reviews/due` ; `POST /library/courses/{id}/reviews/grade` `{section_id, card_index, correct}`
- `GET /library/courses/{id}/anki.tsv` → text/tab-separated Anki deck

- [ ] **Step 1: Failing test** — `TestClient`: upload a tiny PDF (stub provider via dependency override), approve plan, generate, GET a chapter, assert body present; GET anki.tsv returns rows.
- [ ] **Step 2–4:** run-fail → implement → run-pass. Background generation runs synchronously in tests via override.
- [ ] **Step 5: Commit** `feat(api): DB-backed library router + anki export`

### Task 12: In-app SRS on ReviewState

**Files:**
- Create: `backend/services/review.py`
- Test: `backend/tests/test_review.py`

**Interfaces:**
- Produces: `grade_card(session, course_id, section_id, card_index, correct:bool) -> ReviewState` (SM-2-style: update ease/interval/due_at/reps); `due_cards(session, course_id) -> list[ReviewState]`. Reuse the math style from legacy `srs_engine` but operate on `ReviewState` rows.

- [ ] **Step 1: Failing test** — grade a card correct twice; assert interval grows and `due_at` advances. Grade wrong; assert interval resets.
- [ ] **Step 2–4:** run-fail → implement → run-pass.
- [ ] **Step 5: Commit** `feat(srs): ReviewState-backed spaced repetition`

---

## Phase 6 — Frontend reader

### Task 13: API client + library list

**Files:**
- Modify: `frontend/app/lib/api.js` (add `library.*` bindings for the new endpoints)
- Modify: `frontend/app/page.js` (dashboard → list `library` courses with status/progress, link to upload)
- Test: manual (`npm run dev`) — documented check.

- [ ] **Step 1:** Add `library` bindings mirroring Task 11 endpoints.
- [ ] **Step 2:** Rework dashboard to call `library.listCourses()`.
- [ ] **Step 3: Verify** `npm run build` passes; `npm run dev` shows the list against a running backend.
- [ ] **Step 4: Commit** `feat(web): library API client + dashboard`

### Task 14: Plan review + generation trigger

**Files:**
- Modify: `frontend/app/upload/page.js` (multi-PDF upload → show generated plan → Approve → trigger generate, poll progress)
- Test: manual check documented.

- [ ] **Step 1:** Upload posts to `/library/uploads`; render returned plan (sections, objectives, importance, target_words).
- [ ] **Step 2:** Approve button → `/plan/approve` then `/generate`; poll `GET course` progress.
- [ ] **Step 3: Verify** end-to-end against backend with Ollama or a test key.
- [ ] **Step 4: Commit** `feat(web): plan review + generation flow`

### Task 15: Chapter reader + quiz/try-it/cards widgets

**Files:**
- Create: `frontend/app/courses/[id]/chapters/[sid]/page.js`
- Create: `frontend/app/components/Quiz.js`, `frontend/app/components/Markdown.js`
- Modify: `frontend/app/courses/[id]/page.js` (book TOC sidebar from plan/chapters)
- Modify: `frontend/package.json` (add a markdown renderer, e.g. `react-markdown` + `remark-gfm`, and a quiz-block remark handling or client parse)
- Test: manual check documented.

**Interfaces:**
- `Markdown.js` renders `body_md` with GFM tables, images (absolute backend URL), code highlight, and intercepts ```` ```quiz ```` blocks → `<Quiz>`; renders `> ✏️ Try it:` and `<details>` natively.
- `Quiz.js` — multiple choice, instant colorized feedback, "check answers" → explanations, feeds misses to `reviews/grade`.

- [ ] **Step 1:** Build `Markdown.js` + `Quiz.js`.
- [ ] **Step 2:** Chapter page fetches chapter, renders body, "mark complete" → progress endpoint.
- [ ] **Step 3:** Course page renders TOC from plan order; sidebar nav.
- [ ] **Step 4: Verify** `npm run build`; visually confirm a generated chapter renders with inline images + working quiz.
- [ ] **Step 5: Commit** `feat(web): mdBook-style chapter reader with quiz/try-it`

### Task 16: Reviews page + Anki export button

**Files:**
- Modify: `frontend/app/reviews/page.js` (due cards from `library` reviews; grade)
- Modify: chapter or course page (Anki export download button → `GET …/anki.tsv`)
- Test: manual check documented.

- [ ] **Step 1:** Reviews page lists due cards, grade buttons call `reviews/grade`.
- [ ] **Step 2:** Anki export button downloads the TSV.
- [ ] **Step 3: Verify** review interval changes persist; TSV imports into Anki.
- [ ] **Step 4: Commit** `feat(web): reviews page + anki export`

---

## Phase 7 — Cutover & cleanup

### Task 17: Wire as primary, retire legacy generator

**Files:**
- Modify: `backend/main.py` (legacy `/courses` + `/subjects` routers remain only if still referenced; mark deprecated)
- Modify: `README.md` (new flow + env vars: `SOURCEMIND_LLM_PROVIDER`, `SOURCEMIND_LLM_MODEL`, `SOURCEMIND_DB_URL`, `ANTHROPIC_API_KEY`)
- Modify: `scripts/dev.sh` / `scripts/build.sh` (ensure `init_db` runs; deps present)
- Delete (after green): legacy `course_engine.py` micro-competency paths, `notebooklm_service.py`, `decomposition_*` — ONLY once nothing imports them (grep first).

- [ ] **Step 1:** Add `init_db()` call on backend startup (`main.py` lifespan).
- [ ] **Step 2:** `grep -r` for imports of legacy modules; remove only the unreferenced ones.
- [ ] **Step 3: Run full suite** `uv run pytest backend/tests` → all pass; `cd frontend && npm run build` → passes.
- [ ] **Step 4:** Update README + scripts.
- [ ] **Step 5: Commit** `chore: cutover to new pipeline; retire legacy generator`

---

## Self-Review

- **Spec coverage:** pipeline (Tasks 4–10), template (7), word targets (6), importance cards (6,9), pluggable LLM (3), DB single-user (1,2), images (4,8,15), in-app SRS + Anki (11,12,16), tutor chat (11), reader UX (13–15), validate→repair (9). All spec sections map to tasks.
- **Placeholder scan:** none — each task names files, interfaces, a concrete test, and a commit.
- **Type consistency:** `ChapterDraft`, `PlanItem`, `Section`, `ExtractedPage`, `Report/Issue` names are reused consistently across tasks 4–11.
