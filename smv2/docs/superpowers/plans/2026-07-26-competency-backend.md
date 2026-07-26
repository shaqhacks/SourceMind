# Competency Graph Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the frontend's `lib/skills/placeholder.ts` sample data with a real per-course competency graph API (nodes, prerequisite edges, mastery, missed questions), serving the Skill Map, Competency detail, Home skill snapshot, and Tests diagnosis surfaces.

**Architecture:** Reuse the existing `Concept` table (inline-practice feature) as the skill node — it already has course-scoped slugs, labels, a section pointer, and `ConceptMastery` tracking. Add two tables (`ConceptEdge` for prerequisites, `ConceptSectionLink` for where-taught), derive levels and mastery deterministically at read time (no job, no stored scores beyond what exists), and import the graph via an idempotent PUT endpoint fed by a hand-run extraction prompt (zero in-app LLM calls, per the 2026-07-26 office-hours decision).

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (smv2/backend), openapi-typescript client regen, Next.js/Vitest frontend swap.

## Global Constraints

- All work under `smv2/backend/` — never repo `frontend/`.
- Zero LLM calls in any code path of this feature (extraction prompt is hand-run by the owner; the prompt file is documentation).
- New FK-bearing tables register in exactly one list in `app/db/registry.py` AND in `_run_ingest`'s explicit wipe block (registry membership alone does not wipe — ADR-025 precedent).
- Routers stay thin (no `sqlalchemy`/`app.db` imports — enforced by `tests/test_architecture.py`).
- Schema change ⇒ Alembic revision (next after `0012_notes`).
- After any backend schema change: `uv run python -m app.export_openapi ../openapi.json` then `npm run gen:api` — never hand-edit `openapi.json`/`schema.d.ts` (ADR-004).
- Verify loop: backend `cd smv2/backend && uv run pytest -q`, frontend `cd smv2/frontend && npm run typecheck && npm test -- --run`; final gate `cd smv2 && ./build.sh`.
- Tunable product constants (single module, reviewable): mastery weights quiz 0.5 / practice 0.3 / SRS 0.2 (renormalized over available signals); status thresholds struggling < 40 ≤ growing ≤ 70 < solid; weak-prereq gate at 60 (handoff §"State Management & Data").

## Decisions locked here (flag to owner if any feel wrong)

1. **Node = existing `Concept`**, not a new `PrereqConcept` table. Office hours named "PrereqConcept/Edge/Link"; `Concept` IS that node — creating a parallel vocabulary would fragment mastery (`ConceptMastery` already keys on `concept_id`). Import upserts by `(course_id, slug)` so existing concept ids — and therefore mastery history — survive re-imports.
2. **Graph lifecycle = wiped on re-ingest** (joins `Concept` in `REPLACED_ON_REINGEST`). Same tradeoff as highlights (ADR-024): re-upload invalidates section ids the links point at; re-import is one hand-run away.
3. **Import via `PUT /api/courses/{course_id}/skills/graph`** (idempotent full replace of edges/links, concept upsert) rather than a CLI script: testable through TestClient, and gives the UI a future "Import graph" affordance. Cycles and unknown slugs are 422s.
4. **Mastery computed at read time** from three deterministic signals (practice accuracy, SRS state of cards in linked sections, quiz hit/miss attributed through test scope → sections → concepts). Laptop-scale; no caching, no background job.
5. **Missed-question attribution is scope-based, not per-question**: `TestAttempt.results[i]` aligns with `Test.questions[i]`; a test's scope sections come from `Test.section_id` / `chapter_label` (mirroring `tests_service._resolve_missed_card_section_id`). Generation-time per-question concept tagging is a deliberate NON-goal for v1 (deterministic before generative); revisit only if scope attribution proves too coarse.

## File Structure

- Modify: `backend/app/db/models.py` (two new models), `backend/app/db/registry.py`, `backend/app/pipeline/ingest.py` (wipe block), `backend/app/schemas.py`, `backend/app/main.py` (router include)
- Create: `backend/app/db/migrations/versions/0013_concept_graph.py`, `backend/app/services/skills_service.py`, `backend/app/routers/skills.py`, `backend/prompts/v1/prereq_extraction.md`, `backend/tests/test_skills_graph.py`, `backend/tests/test_skills_api.py`
- Modify (frontend swap): `frontend/lib/api/client.ts`, `frontend/components/skills/{SkillMapView,CompetencyDetailView,format,layout}.ts(x)`, `frontend/components/dashboard/SkillSnapshotCard.tsx`, `frontend/components/tests/DiagnosisCard.tsx`, their four test files
- Delete: `frontend/lib/skills/placeholder.ts`
- Append: `docs/decisions.md` (ADR-027)

---

### Task 1: `ConceptEdge` + `ConceptSectionLink` tables, migration, registry, wipe block

**Files:**
- Modify: `backend/app/db/models.py` (after `Concept`, ~line 412), `backend/app/db/registry.py:36-56`, `backend/app/pipeline/ingest.py` (the `_run_ingest` wipe block — find the existing `Note`/`Highlight` deletes and add alongside)
- Create: `backend/app/db/migrations/versions/0013_concept_graph.py` (down_revision `"0012_notes"`)
- Test: `backend/tests/test_skills_graph.py` (new), plus existing `tests/test_architecture.py` + `tests/test_course_delete_cascade.py` must stay green (they reflect metadata and will pick the new tables up automatically)

**Interfaces:**
- Produces: `ConceptEdge(id, course_id, from_concept_id, to_concept_id, created_at)` with `UniqueConstraint("course_id", "from_concept_id", "to_concept_id", name="uq_concept_edges")`; `ConceptSectionLink(id, course_id, concept_id, section_id, rank: int = 0, relevance_md: str | None, created_at)` with `UniqueConstraint("concept_id", "section_id", name="uq_concept_section_links")`. All FKs `ondelete="CASCADE"`, indexed, following `Concept`'s exact column style.

- [ ] **Step 1: Write the failing test** (in `backend/tests/test_skills_graph.py`)

```python
from app.db.engine import session_scope
from app.db.models import Concept, ConceptEdge, ConceptSectionLink


def test_reingest_wipes_concept_graph(client, ingest_course):
    course_id, _, _, _ = ingest_course("with_bookmarks")
    with session_scope() as session:
        a = Concept(course_id=course_id, slug="a", label="A")
        b = Concept(course_id=course_id, slug="b", label="B")
        session.add_all([a, b])
        session.flush()
        session.add(ConceptEdge(course_id=course_id, from_concept_id=a.id, to_concept_id=b.id))
        section_id = session.query(  # any real section of the course
            __import__("app.db.models", fromlist=["Section"]).Section
        ).filter_by(course_id=course_id).first().id
        session.add(ConceptSectionLink(course_id=course_id, concept_id=a.id, section_id=section_id))
        session.commit()

    ingest_course("with_bookmarks", course_id=course_id)  # re-ingest same course

    with session_scope() as session:
        assert session.query(ConceptEdge).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptSectionLink).filter_by(course_id=course_id).count() == 0
```

(Adapt the `ingest_course` re-ingest call to the fixture's real signature — see `tests/test_reingest_idempotency.py` for the established re-ingest idiom, and reuse its helper if one exists. Import `Section` normally at top of file; the inline `__import__` above is only to keep this snippet self-contained.)

- [ ] **Step 2: Run it to verify it fails**: `cd smv2/backend && uv run pytest tests/test_skills_graph.py -q` — expected: ImportError (`ConceptEdge` doesn't exist).
- [ ] **Step 3: Add the two models** to `models.py` (copy `Concept`'s column style verbatim; docstrings: edge = "from must be learned before to"; link = "where a concept is taught; Concept.section_id stays the 'introduced here' pointer").
- [ ] **Step 4: Write migration `0013_concept_graph.py`** — mirror `0012_notes.py`'s structure (op.create_table with the same FK/index/unique names as the models).
- [ ] **Step 5: Register + wipe**: add both classes to `REPLACED_ON_REINGEST` in `registry.py`; add `session.query(ConceptEdge).filter_by(course_id=course_id).delete()` (and the link table) to `_run_ingest`'s wipe block next to the existing `Note` delete — same ordering rationale as ADR-025.
- [ ] **Step 6: Run** `uv run pytest tests/test_skills_graph.py tests/test_architecture.py tests/test_course_delete_cascade.py -q` — expected: PASS (architecture test proves registry coverage; cascade test proves FK wiring).
- [ ] **Step 7: Commit** `feat(smv2): concept graph tables — edges + section links, wiped on re-ingest`

### Task 2: Pure derivation functions — levels, mastery, status

**Files:**
- Create: `backend/app/services/skills_service.py` (top half: pure functions + constants)
- Test: `backend/tests/test_skills_graph.py` (append unit tests — no DB needed)

**Interfaces:**
- Produces (exact signatures Tasks 3–4 consume):
  - `QUIZ_WEIGHT = 0.5; PRACTICE_WEIGHT = 0.3; SRS_WEIGHT = 0.2; STRUGGLING_BELOW = 40; SOLID_ABOVE = 70; WEAK_PREREQ_BELOW = 60`
  - `derive_levels(node_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]` — longest-path depth from roots, 1-based; raises `ValueError("cycle")` on any cycle
  - `mastery_score(practice: float | None, srs: float | None, quiz: float | None) -> int` — each signal in [0,1] or None; weighted mean renormalized over present signals, scaled to 0–100, rounded; all-None → 0
  - `status_for(mastery: int, has_any_signal: bool, weak_prereq: bool) -> str` — `"locked"` (no signal AND weak prereq), `"struggling"`, `"growing"`, `"solid"`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from app.services.skills_service import derive_levels, mastery_score, status_for


def test_derive_levels_longest_path_and_cycle_rejection():
    levels = derive_levels(["a", "b", "c"], [("a", "b"), ("b", "c"), ("a", "c")])
    assert levels == {"a": 1, "b": 2, "c": 3}  # c takes the LONGEST path
    with pytest.raises(ValueError):
        derive_levels(["a", "b"], [("a", "b"), ("b", "a")])


def test_mastery_renormalizes_over_missing_signals():
    assert mastery_score(None, None, None) == 0
    assert mastery_score(1.0, None, None) == 100      # only practice present
    assert mastery_score(0.5, 0.5, 0.5) == 50
    # quiz 0.5 weight vs practice 0.3: (0.5*0 + 0.3*1)/(0.8) = 0.375
    assert mastery_score(1.0, None, 0.0) == 38


def test_status_thresholds_and_locked_gate():
    assert status_for(0, has_any_signal=False, weak_prereq=True) == "locked"
    assert status_for(0, has_any_signal=False, weak_prereq=False) == "growing"  # new, unblocked
    assert status_for(39, True, False) == "struggling"
    assert status_for(70, True, False) == "growing"
    assert status_for(71, True, False) == "solid"
```

- [ ] **Step 2: Run to verify failure** (`ModuleNotFoundError`), **Step 3: implement** (Kahn's algorithm with per-node depth max; plain arithmetic for the rest — no external deps), **Step 4: run to green**, **Step 5: commit** `feat(smv2): deterministic skill level/mastery/status derivation`.

### Task 3: Graph import endpoint — `PUT /api/courses/{course_id}/skills/graph`

**Files:**
- Modify: `backend/app/schemas.py` (`SkillGraphConceptIn`, `SkillGraphSectionRefIn`, `SkillGraphEdgeIn`, `SkillGraphIn`, `SkillGraphImportOut`), `backend/app/main.py` (include router)
- Create: `backend/app/routers/skills.py` (thin), import logic in `backend/app/services/skills_service.py`
- Create: `backend/prompts/v1/prereq_extraction.md`
- Test: `backend/tests/test_skills_api.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 `derive_levels` (cycle check at import).
- Produces: `import_graph(session, course_id, payload: SkillGraphIn) -> SkillGraphImportOut` where `SkillGraphIn = {concepts: [{slug, label, section_refs: [{section_id, rank?, relevance_md?}]}], edges: [{from_slug, to_slug}]}` and `SkillGraphImportOut = {concept_count, edge_count, link_count}`. Semantics: upsert concepts by `(course_id, slug)` (update label, keep id → mastery survives); delete + recreate all edges/links for the course; 422 on cycle, unknown slug in an edge, or a `section_id` not belonging to the course; router does existence-404 for the course then delegates.

- [ ] **Step 1: Failing tests** — four cases:

```python
def _graph(section_id):
    return {
        "concepts": [
            {"slug": "tokenization", "label": "Tokenization", "section_refs": [{"section_id": section_id, "rank": 0, "relevance_md": "Defines tokens."}]},
            {"slug": "counting", "label": "Token counting", "section_refs": []},
        ],
        "edges": [{"from_slug": "tokenization", "to_slug": "counting"}],
    }

def test_import_graph_creates_nodes_edges_links(client, ingest_course): ...
    # PUT → 200 {"concept_count": 2, "edge_count": 1, "link_count": 1}

def test_import_is_idempotent_and_preserves_concept_ids(client, ingest_course): ...
    # PUT twice; concept ids unchanged (seed a ConceptMastery row between puts and assert it survives)

def test_import_rejects_cycle_with_422(client, ingest_course): ...
def test_import_rejects_foreign_section_with_422(client, ingest_course): ...
```

(Fill bodies with the TestClient idiom used across `tests/test_notes_api.py` — create/ingest course via fixtures, hit `client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(sid))`.)

- [ ] **Step 2: run failing**, **Step 3: implement** schemas → service (`import_graph` runs `derive_levels` on the incoming edge set purely as validation) → thin router (`APIRouter(prefix="/api/courses/{course_id}/skills")`, existence check via the same course-lookup helper other routers use, delegate) → `main.py` include. **Step 4: run to green.**
- [ ] **Step 5: Write `backend/prompts/v1/prereq_extraction.md`** — the hand-run prompt: instructs pasting a course's outline + section excerpts, asks for STRICT JSON matching `SkillGraphIn` exactly (embed the JSON shape in the prompt), one concept per teachable skill, edges only where a skill is genuinely required first. Header comment: "HAND-RUN by the owner (office-hours 2026-07-26 decision) — no app code loads this file; it lives here to version the wording alongside the other prompts."
- [ ] **Step 6: Commit** `feat(smv2): skill-graph import endpoint + hand-run extraction prompt`

### Task 4: Read endpoints — map + detail

**Files:**
- Modify: `backend/app/schemas.py`, `backend/app/routers/skills.py`, `backend/app/services/skills_service.py`
- Test: `backend/tests/test_skills_api.py` (append)

**Interfaces:**
- Produces:
  - `GET /api/courses/{course_id}/skills` → `SkillMapOut {nodes: [SkillNodeOut], edges: [SkillEdgeOut]}`; `SkillNodeOut = {id, slug, label, level, mastery: int, status, blocked: bool, unlock_note: str | None}`; `SkillEdgeOut = {from_id, to_id, kind: "met" | "weak"}` (`weak` when the source's mastery < `WEAK_PREREQ_BELOW`).
  - `GET /api/courses/{course_id}/skills/{concept_id}` → `SkillDetailOut {node: SkillNodeOut, taught_in: [{section_id, chapter_label, title, rank, relevance_md}], missed_questions: [{question, your_answer, correct_answer, source_test_id, attempted_at}], blocked_skill_labels: [str], cards_count: int, quiz_correct: int, quiz_wrong: int, fix_plan: {prereq_id, prereq_label, section_id} | null}`; 404 for unknown concept/course.
- Signal assembly (all deterministic, single service function `build_map(session, course_id)` shared by both endpoints):
  - practice: `ConceptMastery` rows → `correct/(correct+wrong)` when the sum > 0.
  - SRS: cards whose `section_id` is in the concept's linked sections (links ∪ `Concept.section_id`); signal = mean over cards with a `ReviewState` of `min(1.0, max(0.0, (last_grade - 1) / 3))` for reviewed cards (grade 1–4 → 0..1); no reviewed cards → None.
  - quiz: for each `Test` of the course with attempts, resolve its scope sections (`Test.section_id` if set, else the sections of `chapter_label` — reuse/extract the resolution already in `tests_service`, see `_resolve_missed_card_section_id` and the chapter resolution at `tests_service.py:56-82`); every concept linked to those sections gets attempt `results[i]["correct"]` tallied into correct/wrong; signal = correct/(correct+wrong).
  - `missed_questions`: latest attempt per test, indices where `results[i]["correct"] is False` → `Test.questions[i]["question"]`, choices[`results[i]["your_answer"]`] vs choices[`correct_index`].
  - `fix_plan`: weakest prerequisite below `WEAK_PREREQ_BELOW` → its top-ranked linked section.

- [ ] **Step 1: Failing tests** — seed via session (concepts, links to real ingested sections, a `ConceptMastery` row, one `Test` + submitted `TestAttempt` with one wrong answer, one card + `ReviewState`), then assert: map returns both nodes with computed mastery/status/levels, edge kind flips to `"weak"` when the prereq's mastery is low; detail returns the missed question verbatim with both answer texts, `cards_count`, `taught_in` ordering by rank, and 404s for a foreign concept id.
- [ ] **Step 2: run failing → Step 3: implement → Step 4: green.** Keep `routers/skills.py` free of any `sqlalchemy`/`app.db` import (architecture test).
- [ ] **Step 5: Commit** `feat(smv2): skill map + competency detail read endpoints`

### Task 5: OpenAPI export, client regen, frontend swap

**Files:**
- Regenerate: `openapi.json`, `frontend/lib/api/schema.d.ts`
- Modify: `frontend/lib/api/client.ts` (add `getSkillMap(courseId)`, `getSkillDetail(courseId, skillId)` following the `request(client.GET(...))` shape; export the generated types), `frontend/components/skills/SkillMapView.tsx`, `CompetencyDetailView.tsx`, `format.ts`, `layout.ts` (retarget imports from `@/lib/skills/placeholder` to the generated types; geometry in `layout.ts` is data-shape-only — keep it), `frontend/components/dashboard/SkillSnapshotCard.tsx`, `frontend/components/tests/DiagnosisCard.tsx`
- Delete: `frontend/lib/skills/placeholder.ts`
- Test: `frontend/__tests__/skills-map.test.tsx`, `skill-detail.test.tsx`, `page.test.tsx` (snapshot card), `tests-page.test.tsx` (diagnosis) — swap placeholder imports for `vi.mock("@/lib/api/client")` fixtures using the generated shapes

**Interfaces:**
- Consumes: Task 4's response shapes via the regenerated client.
- Produces: no component outside these surfaces imports skill data any other way; `SAMPLE_DATA_LABEL` badges and "(sample)" suffixes are deleted app-wide (grep for both before finishing).

- [ ] **Step 1:** `cd smv2/backend && uv run python -m app.export_openapi ../openapi.json && cd ../frontend && npm run gen:api` — diff `schema.d.ts` shows only the new skill types.
- [ ] **Step 2:** Update the four test files FIRST to mock `getSkillMap`/`getSkillDetail` (ok/err factories from `__tests__/support/api-result.ts`) and assert: every node label renders, weak edges render dashed, detail shows real missed-question text, snapshot/diagnosis render from the mocked map and show NO sample badge; add one test per surface for the empty state below. Run — expect failures against the placeholder-driven components.
- [ ] **Step 3:** Swap the components. Empty-graph UX (nodes list empty): an `EmptyState` on the map — title "No skill graph yet", body "Run backend/prompts/v1/prereq_extraction.md against this course and import the JSON via PUT /api/courses/{id}/skills/graph", no CTA button (there is nothing in-app to click yet — honest state); SkillSnapshotCard and DiagnosisCard render nothing (return null) when the map is empty, matching how ReviewCard already hides at zero due.
- [ ] **Step 4:** Delete `lib/skills/placeholder.ts`; `grep -rn "skills/placeholder\|SAMPLE_DATA_LABEL\|(sample)" frontend/` must return nothing.
- [ ] **Step 5:** `npm run typecheck && npx vitest run __tests__/skills-map.test.tsx __tests__/skill-detail.test.tsx __tests__/page.test.tsx __tests__/tests-page.test.tsx` — green. **Step 6: Commit** `feat(smv2): skill surfaces on real competency API, placeholder deleted`

### Task 6: ADR + full gate

- [ ] **Step 1:** Append **ADR-027** to `smv2/docs/decisions.md`: competency graph reuses `Concept` + new edge/link tables (wiped on re-ingest, ADR-024/025 precedent); mastery derived at read time from practice/SRS/quiz signals with the constants above; graph authored by hand-run extraction prompt and imported via PUT (zero in-app LLM calls); per-question concept tagging deliberately deferred.
- [ ] **Step 2:** `cd smv2 && ./build.sh` — full gate green. **Step 3: Commit** `docs(smv2): ADR-027 competency graph`

---

## Explicitly out of scope (independent mini-plan candidates)

Fake/omitted data elsewhere that this plan does NOT touch, each a small standalone backend addition:
1. `CardOut` scheduling fields (`due_at`, `last_grade`) → Flashcards retention/next-review columns.
2. Per-day review history endpoint (from `ReviewLog.graded_at`) → Home "This week" tiles + real streak.
3. `CourseOut.progress_percent` → sidebar course progress bars.
4. Attempt ordinal on `TestAttemptOut` → quiz header "attempt 3".
5. Read-state tracking (per-section read marks) → reader contents checkmarks + chapter-progress callout.
