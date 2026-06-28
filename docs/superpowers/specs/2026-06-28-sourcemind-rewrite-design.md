# SourceMind Rewrite — Design Spec

**Date:** 2026-06-28
**Status:** Approved design, pending spec review → implementation plan
**Goal:** Rewrite SourceMind so that generated lessons read like *The Path to Staff* — verbose, coherent, well-structured chapters built on the real PDF text and images — instead of the current short, fragmented, ungrounded output that nobody can learn from.

---

## 1. Problem statement

Current SourceMind ingests a PDF and uses a local LLM (Ollama / llama3.1) to decompose it into ~76 micro-competencies, then generates lessons as a fixed sequence of short template blocks (`teaching` / `definition` / `worked_example` / `common_mistake` / `self_explanation`). The result is unusable.

Evidence — a real generated "lesson" (the *Integers* section), 268 words total:

> *BLOCK 2: DEFINITION — The source detail to anchor this lesson is: "The ability to work comfortably with negative numbers is essential to success in algebra." Rewrite that in your own words as a definition, rule, or decision you can use while solving.*

For comparison, a *Path to Staff* chapter on the same structural level is ~2,000 words of grounded narrative, runnable/worked examples, complexity tables, "Try it" boxes, an auto-graded section-check quiz, and curated spaced-repetition cards.

Four root defects:

1. **Wrong granularity** — generates per micro-competency (76 fragments), not per coherent section.
2. **Template-as-cage** — the rigid block sequence forces choppy, disconnected fragments.
3. **No grounding** — references "the PDF" instead of actually teaching the extracted content.
4. **Inverted work** — "rewrite this in your own words" makes the *learner* do the teaching.

The rewrite's center of gravity is therefore the **generation pipeline and the lesson format**, not the tech stack.

---

## 2. What stays, what goes

**Keep:** FastAPI backend, Next.js frontend, the upload → outline → plan → lesson+quiz generation flow, background generation jobs, the markdown *body* format for lesson content.

**Remove:** the 76-micro-competency decomposition, the `ConceptMastery` competency-tree machinery, the rigid block-template generator, the word-count-minimum hack, and git-files-as-storage.

**Add:** a source-grounded chapter generator targeting the Path-to-Staff template, a validate→repair quality loop, a pluggable LLM provider, first-class image extraction, a relational DB, and an Anki export.

---

## 3. Architecture & pipeline

```
PDF(s)
  ↓ extract  → real text + images (figures / equation-region crops), with page provenance
  ↓ outline  → real chapters/sections (the book's actual TOC)
  ↓ plan     → per-section: objectives, importance tier, prerequisites, target word count
  ↓           (USER REVIEWS / APPROVES the plan — gate before generation)
  ↓ generate → ONE coherent chapter per section via LLMProvider:
  ↓             feed the section's real extracted text + image refs + plan metadata,
  ↓             instruct it to TEACH that content to the Path-to-Staff template
  ↓ validate → quality gates → targeted repair loop on failure
  ↓ persist  → Chapter row in DB (markdown body + quiz + cards)
  ↓ render   → Next.js mdBook-like reader + in-app SRS + Anki export
```

**Key behavioral shift:** the generator's job changes from *"prompt the student to learn"* to *"teach the source content verbosely."* Source text is fed in as raw material to expand and explain, never referenced as homework.

---

## 4. Chapter template (the quality contract)

Every generated chapter is one section, stored with provenance and gate metadata:

```yaml
# fields carried on the Chapter row (frontmatter-equivalent)
schema_version: 2
course_id: beginning_and_intermediate_algebra
chapter_id: ch-1
section_id: "1-2"
title: Adding and Subtracting Integers
objectives: ["Add integers with unlike signs", "..."]   # from the plan
importance: core            # core | supporting | peripheral
source_pages: [12, 18]      # provenance back to the PDF
assets: [fig-1.2-numberline.png]
target_words: 1700          # computed, source-proportional
word_count: 1840            # actual
status: ready
```

**Body (`body_md`)** — the Path-to-Staff shape, generalized to any domain:

1. **Hook** — 1–2 sentence epigraph: why this matters / where it shows up.
2. **Objectives** — "By the end you can…", 3–5 bullets, from the plan.
3. **Narrative teaching** — several `##` sections building *intuition → mechanics → application*, grounded in the real extracted text, with inline images placed where the figure belongs and tables where they earn their place.
4. **Worked examples** — 2–3 fully worked, step-by-step, each step annotated with *why*. **Domain-adaptive**: runnable code for CS, full solution steps for math, structured reasoning otherwise (auto-detected from source).
5. **✏️ Try it** — 1–3 interleaved active prompts, answer in a collapsed `<details>`.
6. **Common pitfalls** — short, grounded in what learners actually get wrong.
7. **📝 Section Check** — embedded ` ```quiz ` JSON, 4–6 MC, each with `answer` + `explain`, auto-graded client-side.
8. **Spaced-Repetition Cards** — `**Q:** … **A:** …` bullets. **Importance-gated** (see §6), not mandatory.
9. **Going Deeper** *(optional)* — references / harder follow-on problems.

**Markdown conventions** (shared contract between generator, renderer, and Anki builder; deliberately identical to Path-to-Staff so its tooling ports over):

- Quiz: fenced ` ```quiz ` → `{q, options[], answer, explain}`
- Try-it: `> ✏️ Try it:` blockquote + optional `<details>`
- Cards: `## Spaced-Repetition Cards` heading, then `**Q:** … **A:** …` bullets
- Images: plain `![caption](<asset-url>)`

---

## 5. Word count — source-proportional

Target word count is **computed per chapter, not fixed**:

```
target_words = clamp(source_section_words × expansion_factor × importance_weight,
                     soft_floor, soft_ceiling)
```

Long source section → long chapter; short → short. The soft floor/ceiling only catch degenerate (near-empty) or runaway output. The validation gate checks the chapter lands within roughly ±25% of `target_words`, not against a one-size band.

---

## 6. Cards — importance-gated

Cards are curated signal, not filler. The plan assigns each section an **importance tier**, which drives card expectations:

- **core** → cards expected; count scales with concept density, not a flat floor.
- **supporting** → few or none, generator's discretion.
- **peripheral** → typically none.

Gate: *core sections must produce cards; others are optional.*

---

## 7. Data model & storage

**Relational DB**, single-user local, no auth. Default **SQLite** (zero-config local file) via SQLAlchemy; Postgres remains a drop-in for any future hosted mode. Chapters are rows, not committed files. Markdown lives *inside* a TEXT column — the template conventions are about body content and are independent of storage.

Core entities:

```
Course        { course_id, title, status, generation_status, generation_progress,
                generation_last_error, created_at, updated_at }
PlanItem      { section_id, course_id, title, objectives[], importance,
                prerequisites[], target_words }
Chapter       { section_id, course_id, title, objectives[], importance,
                source_pages, assets[], body_md (TEXT), quiz (JSON),
                cards (JSON), word_count, status }
Asset         { asset_id, course_id, url/path, source_page, caption }
ProgressState { section_id, completed, last_viewed_at }
ReviewState   { card_id, section_id, ease, interval, due_at }   # in-app SRS
ChatTurn      { section_id, role, content, created_at }         # tutor chat history
```

`quiz` and `cards` are stored as JSON columns (or child tables) derived from / kept in sync with `body_md`. Images are written to backend-served file storage and referenced by URL in `body_md`.

**Why per-section rows** (vs today's one giant course markdown file): smaller units mean reliable LLM generation/repair, clean targeted regeneration, parallel generation, and durable queryable student state.

---

## 8. Ingestion & images

1. Upload PDF(s) → store original, create `Course` (status `ingesting`).
2. Extract per-page text and images with **PyMuPDF (fitz)** — handles both text and image / figure-region rendering better than pypdf, which matters for math figures and equations.
3. Images: capture embedded rasters **and** rendered figure-region crops → asset storage, each tagged with source page for provenance.
4. **Outline detection** (LLMProvider): page structure → real chapters/sections, each mapped to its page range, extracted text, and images.

---

## 9. Plan generation

The LLMProvider produces `PlanItem`s from the outline:

- `objectives` — concrete "can do" statements per section.
- `importance` — core / supporting / peripheral.
- `prerequisites` — section ordering / dependency hints.
- `target_words` — computed per §5.

The user **reviews and approves the plan** (existing outline-approval gate, upgraded) before any lesson generation runs.

---

## 10. LLM provider abstraction

```
LLMProvider (Protocol):
    complete(prompt, *, system, schema=None) -> str | dict

ClaudeProvider   # default; Sonnet-class for generation, structured output via tool use
OllamaProvider   # local fallback
```

Outline detection, plan generation, chapter generation, the grounding judge, and tutor chat all route through this interface. Provider and model are configured per install (env). Claude is the recommended default for output quality; Ollama keeps a fully-local path. Exact model IDs are confirmed against the Claude API reference at implementation time, not hardcoded here.

---

## 11. Generation control flow & quality gates

Per section, as a background job, parallelizable (respecting prerequisite order for context):

```
ctx    = source_text + image_refs + objectives + importance + target_words
draft  = provider.generate_chapter(ctx, template = PATH_TO_STAFF_TEMPLATE)
report = validate(draft)
while report.fail and rounds < N:
    draft  = provider.repair(draft, report.failures)   # targeted fix, not full retry
    report = validate(draft)
persist Chapter row; bump generation_progress           # incremental → partial course viewable
```

**Validation gates** (this loop is what actually buys the quality jump — load-bearing, not polish):

- word count within ~±25% of `target_words`
- ≥2 worked examples
- ≥1 valid quiz block (4–6 items, every item has `explain`)
- cards present if `importance == core` (else optional)
- ≥1 image referenced if the source section had figures
- **grounding judge** — a separate provider call: *"Does this chapter faithfully teach the provided source? List any unsupported claims."* Drift fails the gate.

Failures trigger targeted repair of the missing piece, not a full regeneration, up to `N` rounds.

---

## 12. Frontend — the reading experience

Reframed from a "study tool" into an mdBook-like reader on top of the DB:

- **Sidebar**: book → chapters in plan sequence, with search.
- **Chapter page**: rendered markdown with inline images, syntax highlighting, tables.
- **Interactive widgets** layered on the markdown conventions: auto-graded quiz (with explanations; misses feed the review queue), Try-it `<details>`, "mark complete."
- **Progress**: persisted to the DB (localStorage is a cache, DB is truth).
- **`/reviews`**: in-app spaced-repetition queue driven by `ReviewState`.
- **Anki export**: a build/endpoint that extracts all quiz blocks + cards to a TSV deck (Path-to-Staff `build_anki_deck.py` conventions).
- **Tutor chat**: kept, per-chapter, grounded in that chapter's content.

---

## 13. Retention — in-app SRS + Anki export

Both, since the backend stays:

- **In-app SRS** — `ReviewState` rows schedule due cards; `/reviews` surfaces them. Reuses the existing SRS scheduling logic, repointed at the new card model.
- **Anki export** — TSV deck generated from the same `quiz` + `cards` data, for students who prefer Anki. Both read one source of card data; no divergence.

---

## 14. Out of scope (YAGNI)

- Multi-user accounts, auth, hosting (single-user local for now; revisit later).
- The legacy NotebookLM / audio-generation service.
- The legacy `md_store` subject format and `data/subjects/`.
- The competency-tree decomposition and its evaluation harness.

---

## 15. Success criteria

1. A generated chapter for a real textbook section reads like a Path-to-Staff chapter: source-proportional length, coherent narrative, grounded in the actual text, with worked examples, inline figures, an auto-graded section check, and (for core sections) cards.
2. No "rewrite this in your own words" meta-prompting; the chapter teaches.
3. Images from the PDF appear inline where they belong.
4. The validate→repair loop rejects fragmented, ungrounded, or under-length drafts.
5. A student can run it locally with no accounts, study chapters, take quizzes, review via in-app SRS, and export an Anki deck.
6. Switching `LLMProvider` between Claude and Ollama requires only config, no code change.
```
