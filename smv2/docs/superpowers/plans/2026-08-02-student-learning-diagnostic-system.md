# Student Learning Diagnostic System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SourceMind's section-attributed weighted “mastery” prototype with a learner-scoped, evidence-led system that extracts book-grounded concepts and observable learning claims, maps every quiz/card to those claims, estimates likely concept struggle with visible uncertainty, and schedules more varied, spaced practice for weak concepts.

**Architecture:** Implement the user's selected B+C hybrid in the first release. Preserve the existing course, reader, quiz, and card surfaces while adding Approach B's four explicit boundaries: a versioned curriculum model, immutable item-to-concept mappings, an append-only learner evidence ledger, and a rebuildable learner-state projection. Build and run the transparent Bayesian baseline, BKT, PFA, and DAS3H-style estimators against the same evidence ledger immediately. The deterministic adaptive-study policy initially consumes the transparent baseline; the other estimators emit shadow predictions until a separate promotion review establishes calibration, delayed prediction, stability, and subgroup performance. No estimator creates a causal misconception diagnosis or hard-locks content.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite WAL, Pydantic/OpenAPI, Next.js App Router, TypeScript, Vitest, pytest. No new runtime dependency is required for the first learner model.

## Plan Status and Governing Review Constraint

This is an implementation plan, not implementation code. The repository's principal-engineer review directive prohibits writing implementation code until the user explicitly confirms and explains the architecture choice. Task 0 is therefore a mandatory stop gate.

## Global Constraints

- Diagnose likely concept-level struggle only; do not claim a named misconception or causal root cause from correctness-only evidence.
- Use quiz and spaced-review performance as the primary evidence channels.
- Support both procedural/quantitative and conceptual/explanatory material.
- Derive the curriculum from the book by default and permit instructor standards, corrections, merges, splits, and supplements.
- Increase concept-targeted review and question frequency; do not hard-lock later material.
- Preserve learner isolation across practice, quizzes, review state, estimates, and recommendations.
- Distinguish `insufficient evidence` from poor performance; never encode missing evidence as zero mastery.
- Retain immutable evidence provenance and mapping versions so historical responses are not silently reinterpreted.
- Keep quiz/application evidence distinct from flashcard/recall evidence in storage and API output.
- Validate content mappings with instructors and validate interventions on delayed, preferably unseen, items.
- Keep diffs staged and reversible; do not drop legacy mastery tables in the initial rollout.
- Follow test-first delivery: each task adds a failing behavior test, proves the failure, implements only that task, reruns targeted tests, and commits independently.
- Regenerate `openapi.json` and `frontend/lib/api/schema.d.ts`; no hand-written frontend response shapes for backend APIs.
- Every new course- or section-referencing model must be registered exactly once in `backend/app/db/registry.py` and covered by re-ingest and course-delete tests.
- Do not call an LLM during interactive grading, map reads, or queue reads. Candidate extraction and question-pool replenishment are durable jobs.

## Architecture Decisions Locked by Research and User Selection

1. `Concept` is a stable curriculum anchor, not a learner score.
2. A `LearningClaim` is an observable performance under a concept and is the smallest diagnostic target.
3. An immutable `EvidenceItem` snapshots one version of a quiz question, practice question, or card and its source provenance.
4. `EvidenceItemConceptLink` is the Q-matrix-style mapping from an item to a primary or supporting learning claim.
5. `LearnerEvidenceEvent` is the append-only source of truth for learner responses.
6. `LearnerConceptState` is a rebuildable projection, never the authoritative history.
7. The concept-map percentage is an estimated current readiness, accompanied by evidence sufficiency and uncertainty; the API does not call it proven mastery.
8. The scheduler selects a concept first and an item second, preventing one memorized card from standing in for concept transfer.
9. Historical section-level quiz attribution is not migrated as trusted negative evidence.
10. Instructor judgments are validation evidence, not infallible ground truth.
11. The user selected Approaches B and C together for the first release. They share one evidence ledger and run concurrently; B supplies the initial learner-facing estimate while C's BKT, PFA, and DAS3H-style estimators immediately record shadow predictions and must earn learner-facing authority through prospective validation.

## Architecture Decision Still Requiring User Confirmation

Choose one first-release identity surface:

- **Local-profile release:** one persistent local learner identity with a separate course learning profile for each class; there is no profile switcher or classroom roster yet.
- **Classroom-profile release:** multiple learner profiles, profile switching, instructor roster, and aggregate instructor diagnostics ship in this plan.

The approved first release is **Local-profile release** because it repairs isolation and creates the correct durable identity boundary without expanding this feature into authentication, enrollment, and classroom authorization. One stable learner owns a distinct `CourseLearningProfile` for each class so evidence, estimates, and preferences can differ between subjects without duplicating the person's identity. Selecting Classroom-profile release later adds the optional Task 1B and expands Tasks 9 and 10.

---

### Task 0: Architecture and Identity Approval Gate

**Files:**
- Review: `sources/research_student_learning_diagnostic_system_2026-08-02.md`
- Review: `.omx/specs/deep-interview-student-learning-diagnostic-model.md`
- Review: `docs/superpowers/plans/2026-08-02-student-learning-diagnostic-system.md`

**Interfaces:**
- Consumes: the user-confirmed diagnostic scope and research synthesis.
- Produces: an explicit choice of Local-profile or Classroom-profile release, plus the user's rationale for choosing same-release B+C with a transparent initial authority boundary.

- [x] **Step 1: Select the model direction** — the user selected Approaches B and C in the first release, sharing the evidence ledger and running concurrently.
- [x] **Step 2: Confirm the first-release identity surface** — one stable local learner with one course-scoped learning profile per class.
- [x] **Step 3: Record the architectural rationale** — course profiles isolate subject-specific learning while preserving identity; immediate challenger execution avoids a later data-platform retrofit while the transparent baseline preserves cold-start interpretability.
- [x] **Step 4: Confirm implementation authorization** — the user explicitly said to implement the approved architecture.

Stop condition: no implementation task starts until all four steps are explicitly satisfied.

---

### Task 1A: Persistent Learner Identity and Cross-Surface Isolation

**Files:**
- Create: `backend/app/db/migrations/versions/0014_learner_profiles.py`
- Create: `backend/app/services/learner_context.py`
- Create: `backend/tests/test_learner_scoping.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/registry.py`
- Modify: `backend/app/routers/practice.py`
- Modify: `backend/app/routers/review.py`
- Modify: `backend/app/routers/tests.py`
- Modify: `backend/app/routers/skills.py`
- Modify: `backend/app/services/practice_service.py`
- Modify: `backend/app/services/srs_service.py`
- Modify: `backend/app/services/tests_service.py`
- Modify: `backend/app/services/skills_service.py`
- Modify: `backend/tests/test_architecture.py`
- Modify: `backend/tests/test_course_delete_cascade.py`
- Modify: existing practice, review, quiz, and skills API tests.

**Interfaces:**
- Produces: `LearnerProfile` as a stable local identity; `CourseLearningProfile` as the learner's course-specific evidence/state boundary; `resolve_learner(request, response)` as the single cookie resolver used by all learner-state endpoints.
- Migration behavior: create one legacy local learner for unscoped review/test history; preserve each distinct existing practice learner key as a profile; when the course has exactly one historical practice learner, associate unscoped legacy review/test history with it, otherwise associate unscoped history with the explicit legacy profile and do not merge profiles.
- Schema changes: add learner identity to `ReviewState`, `ReviewLog`, and `TestAttempt`; make review state unique by learner plus card rather than card alone.

- [x] **Step 1: Write failing isolation tests** proving that two learner cookies can grade the same card independently, submit quiz attempts independently, and receive different skill-map estimates.
- [x] **Step 2: Write migration tests** for an empty database, a single historical practice learner, and multiple historical practice learners with previously global SRS/test data.
- [x] **Step 3: Run the new isolation and migration tests** and verify failures demonstrate the current global-state behavior.
- [x] **Step 4: Add the learner profile schema and migration** with explicit backfill behavior above.
- [x] **Step 5: Centralize learner resolution** and remove duplicate cookie creation logic from the practice router.
- [x] **Step 6: Thread learner identity through practice, review, quiz-attempt, and skill-map reads/writes.**
- [x] **Step 7: Update registry, course-delete, and re-ingest behavior** so learner evidence survives/remaps according to its content references without cross-learner merging.
- [x] **Step 8: Run targeted backend tests**: learner scoping, practice API/service, review/SRS, quiz, skills API, architecture, re-ingest, and cascade.
- [ ] **Step 9: Commit** as `feat(smv2): unify learner identity across practice quiz review and skills`.

Acceptance evidence:

- The same card has independent review schedules for two learners.
- A quiz attempt belongs to exactly one learner.
- Skill-map reads use the requesting learner only.
- The P1 learner-key scoping item in `TODOS.md` can be removed with a test reference.

---

### Task 1B: Optional Classroom Profiles and Instructor Boundary

Run this task only if Task 0 selects Classroom-profile release.

**Files:**
- Create: `backend/app/routers/learners.py`
- Create: `backend/app/services/learners_service.py`
- Create: `backend/tests/test_learners_api.py`
- Create: `frontend/app/course/[courseId]/learners/page.tsx`
- Create: `frontend/components/learners/LearnerRoster.tsx`
- Create: `frontend/__tests__/learner-roster.test.tsx`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Modify: `frontend/lib/api/client.ts`

**Interfaces:**
- Produces: course-scoped learner roster, active learner selection, and an explicit instructor/local-owner actor boundary.
- Does not introduce remote authentication; it is a local classroom-profile surface. Remote/multi-tenant authorization remains a separate security project.

- [ ] **Step 1: Write failing API tests** for create, rename, archive, select, and course isolation.
- [ ] **Step 2: Write failing UI tests** for profile switching and archived-profile behavior.
- [ ] **Step 3: Implement the local roster API and active-profile cookie.**
- [ ] **Step 4: Implement the roster/switcher UI and ensure every learner-state surface refreshes after switching.**
- [ ] **Step 5: Run backend and frontend profile tests plus the cross-surface isolation suite.**
- [ ] **Step 6: Commit** as `feat(smv2): add local classroom learner profiles`.

---

### Task 2: Versioned Curriculum, Concepts, Claims, and Relations

**Files:**
- Create: `backend/app/db/migrations/versions/0015_versioned_curriculum.py`
- Create: `backend/app/services/curriculum_service.py`
- Create: `backend/tests/test_curriculum_models.py`
- Create: `backend/tests/test_curriculum_service.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/registry.py`
- Modify: `backend/app/services/skills_service.py`
- Modify: `backend/tests/test_architecture.py`
- Modify: `backend/tests/test_course_delete_cascade.py`
- Modify: `backend/tests/test_reingest_idempotency.py`

**Interfaces:**
- Produces stable anchors `Concept` and `LearningClaim`.
- Produces immutable/versioned curriculum records: `CurriculumVersion`, `ConceptRevision`, `LearningClaimRevision`, `ConceptRelation`, and `ConceptSourceLink`.
- Relation kinds are exactly: `is_part_of`, `requires`, `recommended_before`, `develops_into`, `related_to`, `equivalent_to`, and `aligns_to_standard`.
- Curriculum versions are `draft`, `published`, or `superseded`; exactly one published version may be current per course.
- Existing binary `ConceptEdge` data migrates to `requires` relations in a legacy-import curriculum version with review state `unverified`.

- [x] **Step 1: Write failing model tests** for stable concept identity across revisions, unique current version, typed relations, aliases, source provenance, and claim membership.
- [x] **Step 2: Write failing re-ingest tests** proving published curriculum and historical source provenance are not deleted when the PDF is re-ingested; changed source links become stale rather than reattached silently.
- [x] **Step 3: Run tests** and verify current `REPLACED_ON_REINGEST` behavior fails the preservation cases.
- [x] **Step 4: Add migration and models** with stable anchors and version records.
- [x] **Step 5: Add curriculum service operations** for draft creation, concept merge/split, claim edits, relation review, publish, and supersede.
- [x] **Step 6: Migrate existing graph data** into an unverified legacy curriculum version without changing current learner-facing output yet.
- [x] **Step 7: Update registry and ingest semantics** so curriculum/evidence history is preserved and source links are explicitly stale when their section disappears.
- [x] **Step 8: Run curriculum, architecture, cascade, ingest, and skills regression tests.**
- [ ] **Step 9: Commit** as `feat(smv2): add versioned curriculum concepts claims and relations`.

---

### Task 3: Book-to-Curriculum Candidate Extraction and Review API

**Files:**
- Create: `backend/app/pipeline/concept_extraction.py`
- Create: `backend/app/routers/curriculum.py`
- Create: `backend/prompts/v2/prereq_extraction.md`
- Create: `backend/tests/test_concept_extraction.py`
- Create: `backend/tests/test_curriculum_api.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_llm_prompts.py`
- Modify: `backend/tests/test_worker_loop.py`

**Interfaces:**
- Produces durable job type `concept_extraction`.
- Extraction input is the ordered course outline plus bounded source excerpts, definitions, examples, exercises, and summaries.
- Extraction output contains concept candidates, observable claim candidates, typed relation candidates, aliases, exact source references, confidence, rationale, and provenance. The model selects only from section IDs provided by SourceMind.
- API operations cover start extraction, read current/draft curriculum, edit candidate, merge, split, add standard alignment, publish, and reject.
- Extraction never mutates a published version; reruns create a new draft.

- [x] **Step 1: Write parser tests** for valid output and rejection of unknown sections, duplicate stable keys, invalid relation kinds, missing source references, cycles among strict `requires` relations, and prompt-injection-shaped source content.
- [x] **Step 2: Write job tests** for idempotent draft reuse, bounded retry, spend-cap enforcement, progress reporting, and orphan reconciliation.
- [x] **Step 3: Write API tests** for draft review operations and atomic publish.
- [x] **Step 4: Run the tests** and verify the new job/router are absent.
- [x] **Step 5: Add the schema-constrained prompt and defensive parser.**
- [x] **Step 6: Implement the durable extraction job** using the existing provider, ledger, retry, and worker patterns.
- [x] **Step 7: Implement thin curriculum routes** delegating all mutations to `curriculum_service.py`.
- [x] **Step 8: Run extraction, API, worker, prompt, architecture, and spend-cap tests.**
- [ ] **Step 9: Commit** as `feat(smv2): extract and review book-grounded curriculum drafts`.

---

### Task 4: Immutable Evidence Items and Explicit Item-to-Claim Mapping

**Files:**
- Create: `backend/app/db/migrations/versions/0016_evidence_items.py`
- Create: `backend/app/services/evidence_items_service.py`
- Create: `backend/tests/test_evidence_items.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/registry.py`
- Modify: `backend/app/pipeline/quiz_generation.py`
- Modify: `backend/app/pipeline/cards_generation.py`
- Modify: `backend/app/pipeline/practice_extraction.py`
- Create: `backend/prompts/v3/quiz.md`
- Create: `backend/prompts/v3/cards.md`
- Create: `backend/prompts/v4/practice_assessment.md`
- Modify: quiz, card-generation, and practice-extraction tests.
- Modify: architecture, cascade, and re-ingest tests.

**Interfaces:**
- Produces immutable `EvidenceItem` snapshots for `quiz_question`, `practice_question`, and `flashcard` sources.
- Produces `EvidenceItemConceptLink` with one required primary claim for diagnostic items and optional supporting/prerequisite claims.
- Mapping fields include role, task type, cognitive demand, authored difficulty band, mapping confidence, source reference, curriculum version, prompt version, model, and review state.
- Existing practice items receive trusted mappings from their explicit concept only after reconciliation to the published curriculum.
- Existing quiz/card content receives `legacy_unmapped` evidence items and is excluded from negative diagnosis until reviewed; section overlap is not treated as a trusted mapping.

- [x] **Step 1: Write failing invariants tests** for immutable content fingerprints, one primary mapping, course/version consistency, and no negative evidence from supporting links.
- [x] **Step 2: Write failing generation tests** proving prompts receive allowed concept/claim IDs and parsers reject invented IDs.
- [x] **Step 3: Write migration tests** proving historical quiz/card content is preserved but marked `legacy_unmapped`.
- [x] **Step 4: Run the tests** and confirm current generation has no explicit mappings.
- [x] **Step 5: Add the migration/models/service** and register lifecycle semantics.
- [x] **Step 6: Make quiz generation claim-first** and create one immutable evidence item per persisted question index.
- [x] **Step 7: Make card generation claim-first** while preserving content-addressed card identity and user-edited-card protections.
- [x] **Step 8: Reconcile practice extraction** against stable curriculum IDs instead of upserting concepts by generated slug.
- [x] **Step 9: Run evidence-item, generation, practice, architecture, cascade, and re-ingest tests.**
- [ ] **Step 10: Commit** as `feat(smv2): map every generated learning item to curriculum claims`.

---

### Task 5: Append-Only Learner Evidence Ledger

**Files:**
- Create: `backend/app/db/migrations/versions/0017_learner_evidence_ledger.py`
- Create: `backend/app/services/evidence_service.py`
- Create: `backend/tests/test_evidence_ledger.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/registry.py`
- Modify: `backend/app/services/practice_service.py`
- Modify: `backend/app/services/tests_service.py`
- Modify: `backend/app/services/srs_service.py`
- Modify: practice, quiz, SRS, architecture, cascade, and re-ingest tests.

**Interfaces:**
- Produces append-only `LearnerEvidenceEvent`.
- Every event contains learner, immutable evidence item, channel, normalized outcome, raw grade/result, event time, elapsed time when available, attempt/session identity, spacing since prior relevant event, and model/mapping version.
- Event source identity is unique so retries and duplicate submissions are idempotent.
- Practice answer -> one `practice` event; each submitted quiz question -> one `quiz` event; each graded card -> one `review` event.
- Historical `ConceptMasteryEvent` rows remain migration-compatible, but production grading no longer writes them and no learner estimate reads them.

- [x] **Step 1: Write failing ledger tests** for one event per source action, retry idempotency, learner isolation, immutable history, and correct spacing calculation.
- [x] **Step 2: Write transaction tests** proving grading and evidence insertion commit or roll back together.
- [x] **Step 3: Run tests** and verify current paths update mutable counters/logs without a common evidence record.
- [x] **Step 4: Add ledger migration/model/service** and lifecycle registry entries.
- [x] **Step 5: Integrate practice submissions** without changing immediate grading UX.
- [x] **Step 6: Integrate per-question quiz submissions** and remove section-level evidence creation from the new path.
- [x] **Step 7: Integrate card reviews** while preserving the existing SM-2 scheduling state.
- [x] **Step 8: Run ledger plus all grading/scheduling regressions.**
- [ ] **Step 9: Commit** as `feat(smv2): record learner evidence across quizzes practice and review`.

---

### Task 6: Transparent Learner-State Projection

**Files:**
- Create: `backend/app/db/migrations/versions/0018_learner_concept_state.py`
- Create: `backend/app/services/learner_model.py`
- Create: `backend/tests/test_learner_model.py`
- Create: `backend/tests/test_learner_model_rebuild.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/registry.py`
- Modify: `backend/app/services/evidence_service.py`
- Modify: `backend/app/services/skills_service.py`
- Modify: `backend/tests/test_skills_api.py`

**Interfaces:**
- Produces rebuildable `LearnerConceptState` containing nullable readiness estimate, quiz estimate, review estimate, posterior uncertainty, effective evidence count, distinct item count, distinct session count, trend, status, last evidence time, model version, and calculation time.
- Produces pure `estimate_claim_state(events, now, config)` and `roll_up_concept(claim_states, claim_importance)` functions.
- Model v1 uses a weak Beta prior and weighted effective successes/failures. Quiz correctness contributes full primary evidence; card grades contribute a lower configurable evidence weight; supporting mappings never receive negative evidence in v1; repeated same-item evidence is discounted; elapsed time and card stability inform forgetting risk.
- Default classification requires evidence across multiple unique items and occasions. Exact thresholds live in a versioned configuration and are labeled pilot hypotheses, not universal research facts.
- `insufficient_evidence` is returned when the evidence gate is unmet. `likely_struggling` requires the uncertainty-aware upper estimate to remain below the target; `retained` requires the lower estimate to meet the target; intermediate cases are `watch` or `building`.

- [x] **Step 1: Write failing pure-model tests** covering no evidence, one correct answer, repeated same-item cramming, multiple spaced failures, mixed quiz/review signals, recovery on delayed varied items, forgetting risk, and supporting-link credit isolation.
- [x] **Step 2: Write failing projection tests** for idempotent rebuild, model-version change, learner isolation, concept merge/split history, and stale mapping exclusion.
- [x] **Step 3: Write failing API regression tests** proving one correct response cannot display 100 readiness and missing evidence does not display zero.
- [x] **Step 4: Run tests** and verify the current fixed weighted model violates the cases.
- [x] **Step 5: Add the projection schema and pure learner model.**
- [x] **Step 6: Recompute affected claims/concepts after each committed event** and provide a full deterministic rebuild path.
- [x] **Step 7: Switch skill reads to learner-state projections** and remove the temporary compatibility response fields.
- [x] **Step 8: Run learner-model, rebuild, skills, grading, and review regressions.**
- [ ] **Step 9: Commit** as `feat(smv2): derive uncertainty-aware learner concept states`.

---

### Task 6B: Shadow Knowledge-Tracing and Cognitive-Diagnostic Challengers

This task implements the Approach C portion of the same first-release B+C architecture. Its code ships in the same release, while its implementation still follows Tasks 4–6 because the estimators require reviewed mappings, an immutable ledger, and a reproducible baseline interface.

**Files:**
- Create: `backend/app/services/learner_model_challengers.py`
- Create: `backend/app/services/learner_model_evaluation.py`
- Create: `backend/tests/test_learner_model_challengers.py`
- Create: `backend/tests/test_learner_model_evaluation.py`
- Create: `docs/validation/challenger-model-promotion.md`
- Modify: `backend/app/db/migrations/versions/0018_learner_concept_state.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/registry.py`
- Modify: `backend/app/services/evidence_service.py`
- Modify: `backend/tests/test_course_delete_cascade.py`

**Interfaces:**
- Produces a common learner-model interface over the same versioned evidence snapshot used by the production baseline.
- Produces immutable, timestamped shadow predictions with model name/version, training cutoff, feature-schema version, curriculum/mapping version, prediction horizon, and target definition.
- BKT, PFA, and a DAS3H-style recency/spacing estimator are all implemented and invoked immediately; each records `insufficient_data` rather than a numeric prediction when its own data gate is unmet.
- Multi-skill cognitive-diagnostic and sequence models remain disabled until identifiability, sample-size, missingness, and mapping-quality gates in the promotion protocol are met.
- Shadow predictions never alter the learner-facing percentage, classification, or study queue. Promotion requires a separate reviewed decision and rollback plan.

- [x] **Step 1: Write failing contract tests** proving all models consume the same frozen evidence snapshot, cannot read future events, and emit comparable prediction records.
- [x] **Step 2: Write failing synthetic-recovery tests** for BKT/PFA parameter behavior, sparse learners, unseen claims, duplicate items, and concept-version changes.
- [x] **Step 3: Write failing evaluation tests** for temporal train/evaluation splits, calibration, log loss/Brier score, delayed correctness, bootstrap uncertainty, subgroup reporting, and baseline comparison.
- [x] **Step 4: Define hard data gates** for minimum learners, attempts, unique items, occasions, mapping-review coverage, and outcome prevalence before each challenger may train or be reported.
- [x] **Step 5: Implement the common interface and immutable shadow-prediction storage.**
- [x] **Step 6: Implement BKT and PFA challengers** without connecting them to production reads or scheduling.
- [x] **Step 7: Implement and invoke the DAS3H-style challenger immediately; record `insufficient_data` until its spacing-data gate passes, and keep DCM/neural adapters disabled until their documented gates pass.**
- [x] **Step 8: Run leakage, synthetic-recovery, calibration, stability, and subgroup tests against the transparent baseline.**
- [x] **Step 9: Write the promotion protocol** specifying prospective evaluation, non-inferiority floors, interpretability review, rollback triggers, and approval ownership.
- [ ] **Step 10: Commit** as `feat(smv2): evaluate knowledge tracing models in shadow mode`.

Acceptance evidence:

- Every challenger prediction can be reproduced from a frozen ledger cutoff and versioned configuration.
- No challenger receives post-cutoff evidence or changes production behavior.
- Results are withheld when data gates fail rather than filled with unstable estimates.
- A challenger cannot be promoted merely because it fits historical training data better.

---

### Task 7: Concept-First Adaptive Study Queue

**Files:**
- Create: `backend/app/services/adaptive_study_service.py`
- Create: `backend/app/routers/study.py`
- Create: `backend/app/pipeline/concept_practice_generation.py`
- Create: `backend/prompts/v1/concept_practice.md`
- Create: `backend/tests/test_adaptive_study_service.py`
- Create: `backend/tests/test_study_api.py`
- Create: `backend/tests/test_concept_practice_generation.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/srs_service.py`
- Modify: worker, prompt, spend-cap, and review tests.

**Interfaces:**
- Produces `GET /api/courses/{course_id}/study/queue`, returning a deterministic ordered union of flashcard and multiple-choice activities with concept ID, reason, readiness state, due metadata, and activity payload.
- Produces durable `concept_practice_generation` jobs that replenish a concept's reviewed item pool outside interactive requests.
- Concept priority combines performance gap, diagnostic confidence, forgetting risk, curriculum importance, and overdue state; exact coefficients are model-versioned pilot configuration.
- Queue policy caps targeted remediation, reserves coverage/exploration capacity, prefers varied/unseen items, and never returns an unreviewed or stale-mapped item as diagnostic evidence.
- Existing `/review/queue` remains functional during migration and delegates card-only callers to the same learner-scoped scheduling data.

- [x] **Step 1: Write failing priority tests** for weak concepts, insufficient-evidence exploration, due-card preservation, remediation caps, deterministic tie-breaking, varied-item preference, and no starvation of other concepts.
- [x] **Step 2: Write failing queue API tests** for mixed activity types, learner isolation, empty state, and no synchronous LLM calls.
- [x] **Step 3: Write failing generation-job tests** for claim/source grounding, allowed-ID validation, pool deduplication, retry, and spend cap.
- [x] **Step 4: Run tests** and verify the current queue only sorts due cards.
- [x] **Step 5: Implement deterministic concept priority and item selection.**
- [x] **Step 6: Implement the mixed study API and preserve the existing card queue contract.**
- [x] **Step 7: Implement asynchronous concept-practice replenishment.**
- [x] **Step 8: Run study, SRS, jobs, prompts, spending, and learner-model tests.**
- [ ] **Step 9: Commit** as `feat(smv2): schedule concept-targeted adaptive study activities`.

---

### Task 8: Learner-Facing Concept Map and Mixed Review Experience

**Files:**
- Regenerate: `openapi.json`
- Regenerate: `frontend/lib/api/schema.d.ts`
- Modify: `backend/app/schemas.py`
- Modify: `frontend/lib/api/client.ts`
- Modify: `frontend/lib/hooks/useSkillMap.ts`
- Modify: `frontend/components/skills/SkillMapView.tsx`
- Modify: `frontend/components/skills/CompetencyDetailView.tsx`
- Modify: `frontend/components/skills/format.ts`
- Modify: `frontend/lib/skills/derive.ts`
- Modify: `frontend/components/dashboard/SkillSnapshotCard.tsx`
- Modify: `frontend/components/tests/DiagnosisCard.tsx`
- Modify: `frontend/app/review/page.tsx`
- Modify: skill-map, skill-detail, skills-derive, dashboard, tests-page, and review-page tests.

**Interfaces:**
- Replaces `mastery` with nullable `readiness_estimate` plus `evidence_state`, `uncertainty`, channel estimates, evidence counts, trend, last evidence time, and an evidence-backed explanation.
- Removes `rootCause` and hard `blocked` language from learner-facing derivations.
- Review UI renders flashcard activities with reveal/grade controls and question activities with answer/feedback controls.
- Concept detail exposes “Why this estimate,” linked learning claims, quiz evidence, review evidence, next activity, and relevant reading.

- [x] **Step 1: Update frontend tests first** to assert insufficient-evidence rendering, uncertainty labels, separate quiz/review evidence, absence of causal “why you're stuck” language, and mixed review activity behavior.
- [x] **Step 2: Update backend response-model tests** for nullable estimates and evidence explanations.
- [x] **Step 3: Regenerate OpenAPI and TypeScript types** and confirm the generated diff contains only intended contract changes.
- [x] **Step 4: Update the API client and hooks** without hand-written backend response shapes.
- [x] **Step 5: Update the skill map/detail/dashboard/diagnosis surfaces** to use evidence-aware copy.
- [x] **Step 6: Update the review page** to consume the mixed study queue and preserve keyboard behavior for cards.
- [x] **Step 7: Search the frontend** for obsolete `mastery`, `rootCause`, `blocked`, and “why you're stuck” semantics; retain only explicitly legacy or migration-test references.
- [x] **Step 8: Run TypeScript typecheck and targeted Vitest suites.**
- [ ] **Step 9: Commit** as `feat(smv2): show evidence-aware readiness and adaptive review`.

---

### Task 9: Instructor Curriculum Review and Diagnostic Agreement

**Files:**
- Create: `backend/app/db/migrations/versions/0019_diagnostic_validation.py`
- Create: `backend/app/services/diagnostic_validation_service.py`
- Create: `backend/app/routers/diagnostic_validation.py`
- Create: `backend/tests/test_diagnostic_validation.py`
- Create: `frontend/app/course/[courseId]/curriculum/page.tsx`
- Create: `frontend/app/course/[courseId]/diagnostics/validate/page.tsx`
- Create: `frontend/components/curriculum/CurriculumReview.tsx`
- Create: `frontend/components/diagnostics/DiagnosticValidation.tsx`
- Create: `frontend/__tests__/curriculum-review.test.tsx`
- Create: `frontend/__tests__/diagnostic-validation.test.tsx`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Modify: `frontend/lib/api/client.ts`
- Modify: course navigation.

**Interfaces:**
- Produces instructor editing for concepts, claims, relations, mappings, and standards alignment.
- Produces blinded instructor judgments of `insufficient`, `not_struggling`, `uncertain`, or `likely_struggling` at the concept level before revealing the model state.
- Produces agreement summaries by course, concept, domain/task type, and evidence sufficiency; disagreements require a reason category: model estimate, item mapping, concept granularity, insufficient student evidence, or instructor disagreement.
- Local-profile release treats the local owner as the instructor/reviewer. Classroom-profile release adds roster filtering and per-learner selection.

- [x] **Step 1: Write failing curriculum-review tests** for edits creating a new draft/version without rewriting historical evidence.
- [x] **Step 2: Write failing blinded-judgment tests** proving model state is not returned before the judgment is recorded.
- [x] **Step 3: Write failing aggregation tests** for raw agreement, chance-adjusted agreement, per-concept disagreement, and insufficient sample reporting.
- [x] **Step 4: Implement validation storage/service/routes** and register lifecycle behavior.
- [x] **Step 5: Implement curriculum and diagnostic review UI.**
- [x] **Step 6: Regenerate API types and run backend/frontend validation suites.**
- [ ] **Step 7: Commit** as `feat(smv2): add instructor curriculum and diagnosis validation`.

---

### Task 10: Delayed-Retention Experiment Instrumentation

**Files:**
- Create: `backend/app/services/retention_study_service.py`
- Create: `backend/app/routers/retention_studies.py`
- Create: `backend/tests/test_retention_study.py`
- Create: `docs/validation/student-learning-model-pilot.md`
- Modify: `backend/app/db/migrations/versions/0019_diagnostic_validation.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/adaptive_study_service.py`

**Interfaces:**
- Produces workload-matched concept-level assignment to `adaptive_targeted` or `baseline_review` for eligible learner-concept pairs.
- Produces delayed retention probes using unseen, reviewed evidence items aligned to the same claim.
- Primary outcome is delayed correctness on representative items; secondary outcomes include longer-delay performance, transfer task performance, study workload, completion, and instructor agreement.
- Assignment is immutable and reproducible from stored study/version metadata; the scheduler cannot change groups after observing outcomes.

- [x] **Step 1: Write failing randomization tests** for reproducibility, balance, eligibility, and immutable assignment.
- [x] **Step 2: Write failing leakage tests** proving retention probes are not shown during treatment and do not reuse treatment items.
- [x] **Step 3: Write failing outcome tests** for delayed windows, workload accounting, attrition reporting, and no causal summary below sample thresholds.
- [x] **Step 4: Implement study assignment, probe scheduling, and outcome export.**
- [x] **Step 5: Integrate study group into adaptive queue selection without changing non-study behavior.**
- [x] **Step 6: Write the pilot protocol** including consent/privacy assumptions, outcome definitions, stopping rules, and analysis limitations.
- [x] **Step 7: Run retention-study, adaptive-study, evidence, and learner-model tests.**
- [ ] **Step 8: Commit** as `feat(smv2): instrument delayed retention validation`.

---

### Task 11: Compatibility Removal, ADR, and Full Verification

**Files:**
- Modify: `backend/app/services/skills_service.py`
- Modify: `backend/app/services/practice_service.py`
- Modify: `backend/app/schemas.py`
- Modify: `frontend/lib/skills/derive.ts`
- Modify: `TODOS.md`
- Modify: `docs/decisions.md`
- Modify: `sources/research_student_learning_diagnostic_system_2026-08-02.md` only if implementation evidence changes a research inference.
- Modify: tests that intentionally cover the legacy compatibility adapter.

**Interfaces:**
- Removes runtime reads of fixed weighted `mastery_score`, section-scoped quiz attribution, cross-learner aggregation, hard lock status, and root-cause UI derivation.
- Leaves legacy database tables in place for one release as rollback/audit data; marks them deprecated and stops new writes only after ledger parity tests pass.
- Adds an ADR defining concept/claim/evidence/state boundaries, learner identity, score semantics, model versioning, adaptive policy, validation gates, and deferred work.

- [x] **Step 1: Add parity/audit tests** comparing source actions with ledger events and projection rebuilds before disabling legacy writes.
- [x] **Step 2: Remove the compatibility adapter from API responses** and regenerate OpenAPI/client types.
- [x] **Step 3: Disable new `ConceptMastery`/`ConceptMasteryEvent` writes** while preserving historical rows.
- [x] **Step 4: Remove fixed weights, section-attribution logic, blocking thresholds, and root-cause derivations from production paths.**
- [x] **Step 5: Update `TODOS.md`** to remove resolved learner scoping and replace it with any measured pilot/calibration follow-ups.
- [x] **Step 6: Append the ADR** with the approved architecture and validation boundaries.
- [x] **Step 7: Run backend targeted suites** for migrations, identity, curriculum, extraction, evidence items, ledger, learner model, adaptive study, instructor validation, retention studies, re-ingest, cascade, architecture, worker, prompts, spend cap, practice, quizzes, review, and skills.
- [x] **Step 8: Run frontend targeted suites** for curriculum, diagnostics, skills, dashboard, tests, and mixed review.
- [ ] **Step 9: Run `./build.sh`** and require compile, backend tests, OpenAPI freshness, frontend typecheck, tests, and build to pass.
- [x] **Step 10: Run `git diff --check` and repository searches** proving obsolete runtime semantics are gone.
- [ ] **Step 11: Perform a manual local smoke test**: ingest a procedural book and a conceptual book; extract/review curriculum; answer mixed quiz/card evidence as two learners when applicable; observe different estimates; verify targeted queue behavior; record instructor judgment; complete a delayed probe.
- [ ] **Step 12: Commit** as `docs(smv2): define and verify evidence-led learning model`.

---

## Required Verification Matrix

| Requirement | Authoritative evidence |
| --- | --- |
| Learner isolation | Two-profile integration tests across practice, quiz, SRS, map, and study queue |
| Book-derived concepts with instructor correction | Extraction fixtures plus curriculum version/edit/publish API and UI tests |
| Both domain families | One procedural and one conceptual extraction/generation fixture plus smoke test |
| Explicit question/card mappings | Database invariants and generation parser tests rejecting unknown IDs |
| No single-answer 100% claim | Learner-model and skills API regression tests |
| Missing evidence is not zero | API and UI insufficient-evidence tests |
| Quiz and review both contribute | Channel-specific learner-model tests and detail response assertions |
| Repetition/spacing affects estimate | Same-item cramming, delayed varied-success, and forgetting tests |
| Same-release B+C architecture | Shadow-model invocation, leakage, reproducibility, data-gate, calibration, and baseline-comparison tests |
| Weak concept increases review | Adaptive queue priority integration test |
| More questions are available | Concept-practice durable job and pool-replenishment test |
| No hard content lock | API/UI regression search and navigation test |
| Instructor agreement is measurable | Blinded judgment and aggregation tests |
| Retention is measurable | Immutable assignment, unseen delayed probe, and workload-matched outcome tests |
| Re-ingest preserves history honestly | Curriculum/evidence stale-link and remapping tests |
| Full repository remains healthy | Fresh successful `./build.sh` output |

## Rollout and Reversibility

1. Ship learner scoping first; it fixes a current P1 defect independently.
2. Add curriculum/evidence tables without changing learner-facing responses.
3. Dual-write the evidence ledger and compare it to current source actions.
4. Run the transparent learner projection and adaptive policy behind a course-level feature flag.
5. Ship and invoke BKT, PFA, and DAS3H-style estimators in the same release; record `insufficient_data` where necessary and do not expose their scores or scheduling choices.
6. Switch map/detail reads after baseline parity, calibration, and instructor-review checks pass.
7. Switch review sessions to the mixed queue while retaining `/review/queue` compatibility.
8. Consider challenger promotion only through the documented prospective gate and a separate architecture review.
9. Disable legacy mastery writes only after rebuild and rollback tests pass.
10. Keep legacy tables for one release; dropping them requires a separate destructive migration approval.

## Self-Review Record

- Spec coverage: every confirmed requirement maps to Tasks 1–11, including Task 6B, and the verification matrix.
- Brownfield risks covered: learner-key leak, global SRS state, unscoped test attempts, slug identity, section-level attribution, re-ingest lifecycle, OpenAPI generation, durable jobs, spend cap, and UI causal language.
- No new dependency required for model v1.
- No destructive table drop included.
- The approved B+C selection is captured as a same-release multi-estimator architecture with an explicit learner-facing authority boundary; Task 0 is resolved.
- Implementation code examples are intentionally omitted because the user's standing principal-engineer directive prohibits implementation code before architectural explanation and approval.
