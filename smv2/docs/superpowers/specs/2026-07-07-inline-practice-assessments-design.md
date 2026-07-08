# Inline Practice Assessments Design

Date: 2026-07-07
Status: Draft for user review

## Goal

Turn textbook practice sections into inline multiple-choice assessments on the chapter test page. The questions, answers, and grading must be grounded in the textbook. The system should generate/extract only what is needed when the user visits the page, cache the extracted questions globally for the course section, and keep user attempts and concept mastery user-specific.

## Decisions

- Use dedicated practice assessment models instead of overloading the existing `Test` and `TestAttempt` deck flow.
- Extract lazily per practice section, then cache globally per course/section/source version.
- Use the textbook answer key as the source of truth for correct answers.
- Do not extract all answer keys upfront. Extract the answer-key slice needed for the current practice section when that section is requested.
- Grade each question immediately after the user chooses an answer.
- Reveal the correct answer and explanation immediately after grading.
- Update concept mastery per question, not per section.
- Count only the learner's first submitted answer for a question toward concept mastery. Later resubmits return the existing result and do not change points again.

## Existing Context

The current quiz system stores generated chapter quiz decks in `tests.questions` and stores whole-test submissions in `test_attempts`. That flow is useful for generated quizzes, but it is not shaped for inline per-question grading, source-backed answer keys, or concept mastery updates.

The current practice section rendering also cannot rely on `sections.body_md` alone for math display. The extracted markdown can be lossy for fractions and equations. The new extraction pipeline should use the original `Section` metadata, source `Asset` page range, and matching answer sections as inputs. The previously added original-page rendering can remain as a fallback when structured practice extraction fails or is still generating.

The repository does not currently expose a user/account model in the inspected backend models. This design uses `learner_key` as the owner field for attempts and mastery. If authentication exists later, `learner_key` should become the authenticated user id. Until then, it should be an opaque server-issued anonymous learner id stored in a secure cookie.

## Data Model

### `concepts`

Global course concepts that questions can affect.

- `id`: UUID primary key
- `course_id`: foreign key to `courses`, cascade delete
- `slug`: stable course-local identifier such as `fractions.simplify`
- `label`: user-facing name such as `Simplifying Fractions`
- `chapter_label`: nullable source chapter label
- `section_id`: nullable source section that introduced or primarily uses the concept
- `created_at`
- `updated_at`

Constraints:

- Unique on `(course_id, slug)`.

### `practice_questions`

Cached textbook-backed questions for one practice section.

- `id`: UUID primary key
- `course_id`: foreign key to `courses`, cascade delete
- `chapter_label`: exact chapter label used by the course outline
- `section_id`: foreign key to the practice `sections` row
- `concept_id`: foreign key to `concepts`
- `source_asset_id`: nullable foreign key to `assets`
- `source_page_start`: nullable 1-based page number
- `source_page_end`: nullable 1-based page number
- `problem_number`: textbook problem number or stable extracted ordinal
- `source_ref`: compact source reference, for example `0.2 Practice - Fractions #12`
- `answer_section_id`: nullable foreign key to the matching answer-key `sections` row
- `answer_source_ref`: compact answer reference, for example `Chapter 0 Answers #12`
- `stem_md`: safe Markdown/LaTeX stem to render
- `choices`: JSON array of safe Markdown/LaTeX answer choices
- `correct_index`: integer index into `choices`
- `explanation_md`: safe Markdown/LaTeX explanation grounded in the textbook answer and the problem
- `source_fingerprint`: hash of section content hash, answer source, problem number, and extraction version
- `extraction_version`: version string for the extraction prompt/parser
- `confidence`: float from 0 to 1 for extraction and answer mapping confidence
- `status`: `ready`, `low_confidence`, or `invalid`
- `created_at`
- `updated_at`

Constraints:

- Unique on `(course_id, section_id, source_fingerprint)`.
- Only `ready` questions are shown as graded questions.
- Questions with no mapped textbook answer are not made gradeable.

### `practice_extraction_runs`

Tracks lazy extraction state and prevents duplicate concurrent generation.

- `id`: UUID primary key
- `course_id`: foreign key to `courses`, cascade delete
- `section_id`: foreign key to `sections`, cascade delete
- `status`: `queued`, `running`, `ready`, or `failed`
- `job_id`: nullable foreign key to existing `jobs`
- `input_fingerprint`: hash of the practice section, answer sections, and extraction version
- `question_count`
- `error`: nullable safe error summary
- `created_at`
- `updated_at`

Constraints:

- Unique active run on `(course_id, section_id, input_fingerprint)`.

### `practice_answers`

One learner's first answer for a practice question.

- `id`: UUID primary key
- `course_id`: foreign key to `courses`, cascade delete
- `question_id`: foreign key to `practice_questions`, cascade delete
- `learner_key`: opaque learner id
- `selected_index`
- `correct`
- `points_delta`
- `answered_at`

Constraints:

- Unique on `(learner_key, question_id)`.
- A duplicate submission returns this row and does not create another mastery event.

### `concept_masteries`

Fast aggregate of a learner's current points for a concept.

- `course_id`: foreign key to `courses`, cascade delete
- `concept_id`: foreign key to `concepts`, cascade delete
- `learner_key`: opaque learner id
- `points`: integer mastery points
- `correct_count`
- `wrong_count`
- `updated_at`

Primary key:

- `(course_id, concept_id, learner_key)`.

### `concept_mastery_events`

Append-only scoring ledger so mastery can be audited or recalculated.

- `id`: UUID primary key
- `course_id`
- `concept_id`
- `question_id`
- `practice_answer_id`
- `learner_key`
- `delta`: `+1` for correct, `-1` for wrong
- `created_at`

The aggregate `concept_masteries.points` is updated from these events. Version one uses `+1` for correct and `-1` for wrong with no storage clamp. The UI can map points to labels later without changing the event history.

## Extraction Flow

1. The frontend requests practice assessment data for a section.
2. The backend checks for `ready` `practice_questions` for that course and section.
3. If questions exist, return them without correct answers.
4. If questions do not exist and no extraction run exists, return `not_started`.
5. The frontend starts extraction with a state-changing `POST`.
6. The backend computes an input fingerprint from:
   - practice section id and `content_hash`
   - practice source page range
   - chapter answer sections and their `content_hash`
   - extraction version
7. If a matching extraction run is already `queued` or `running`, return `generating`.
8. If no active run exists, create a `practice_extraction_runs` row and enqueue a job.
9. The job extracts only the problems and matching answers needed for the requested section.
10. The job stores `concepts` and `practice_questions`.
11. The frontend polls the read-only `GET` endpoint until the status is `ready`, then displays the questions.

The extractor may use an LLM to structure messy textbook text, assign concepts, generate explanations, and create distractor choices. The correct answer must come from the textbook answer-key mapping. If the answer key cannot be mapped with acceptable confidence, that problem is excluded from gradeable questions or marked `low_confidence` for later review.

## API Design

### `GET /api/courses/{course_id}/sections/{section_id}/practice-assessment`

Returns the current extraction state. This endpoint is read-only and must not create jobs or mutate database state.

Ready response:

- `status: "ready"`
- `section_id`
- `questions`: array of redacted questions:
  - `id`
  - `problem_number`
  - `source_ref`
  - `stem_md`
  - `choices`
  - `concept`: `{ id, slug, label }`
  - `answered`: optional existing answer summary for the current learner

Generating response:

- `status: "generating"`
- `run_id`
- `message`

Failed response:

- `status: "failed"`
- `message`

Not-started response:

- `status: "not_started"`
- `message`

This endpoint must never include `correct_index` for unanswered questions.

### `POST /api/courses/{course_id}/sections/{section_id}/practice-assessment`

Idempotently starts lazy extraction for a practice section. If an equivalent extraction run already exists, returns that run instead of creating another. This state-changing endpoint replaces the earlier side-effecting GET design so page loads, crawlers, and prefetches cannot create jobs.

Response:

- `status: "generating"` or `status: "failed"`
- `section_id`
- `run_id`
- `job_id`
- `message`

### `POST /api/courses/{course_id}/practice-questions/{question_id}/answer`

Request:

- `selected_index`

Response:

- `question_id`
- `selected_index`
- `correct`
- `correct_index`
- `explanation_md`
- `concept`: `{ id, slug, label }`
- `points_delta`
- `mastery_points`
- `already_answered`: boolean

The backend derives `learner_key`, loads the question through the supplied `course_id`, validates `selected_index`, checks the answer, creates the first answer row if absent, records a mastery event, updates the aggregate mastery row, and returns the result. If the learner already answered the question, the endpoint returns the original result with `already_answered: true` and does not apply another score change.

## Frontend Behavior

The chapter test page should show inline practice assessments for practice sections.

- If extraction is not ready, show a compact generating state for that section and poll.
- When ready, render each question with clean Markdown/LaTeX math.
- Choices are buttons or radio controls.
- On selection, submit to the backend.
- After the response, lock the question, show correct/incorrect state, reveal the correct answer, and render the explanation.
- Display the concept label and updated concept points near the result.
- Keep existing generated chapter quiz actions separate from inline practice assessments.
- Keep original textbook page rendering as a fallback or secondary "view source" affordance, not the primary test interaction.

## Security Requirements

- Treat all extracted textbook text and LLM output as untrusted.
- Do not render raw HTML from extraction output.
- Store and render only safe Markdown/LaTeX through the existing sanitized rendering path.
- Do not expose `correct_index` before the learner answers.
- Grade only on the backend.
- Validate that the question belongs to the requested course before grading.
- Validate `selected_index` against the stored `choices` length.
- Use parameterized ORM queries only.
- Use an opaque server-issued learner id until real authentication exists.
- Set the learner cookie with `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
- Do not let the answer endpoint create or mutate global cached questions.
- Use existing LLM spend controls and job tracking so page visits cannot trigger unbounded generation.

## Error Handling

- Missing practice section: return 404.
- Section is not `kind="practice"`: return 400.
- No matching answer-key section: return `failed` with a user-safe message and keep source page fallback available.
- Low-confidence answer mapping: exclude the problem from gradeable questions.
- Extraction job failure: store the safe error on `practice_extraction_runs` and return `failed`.
- Duplicate answer submission: return the first recorded result without changing mastery again.
- Deleted course or re-ingest: cascade old questions, runs, answers, and mastery rows with the course. Section re-ingest changes the input fingerprint and causes a fresh lazy extraction when requested.

## Testing Plan

Backend tests:

- Lazy request creates one extraction run when no cached questions exist.
- Concurrent lazy requests reuse the same active extraction run.
- Ready request returns questions without `correct_index`.
- Extraction stores textbook-answer-backed questions and excludes unmapped answers.
- Answer submission returns immediate correctness, explanation, and concept point delta.
- Wrong answer creates a `-1` mastery event.
- Correct answer creates a `+1` mastery event.
- Duplicate answer does not create a second event or change mastery twice.
- Question ids cannot be graded across the wrong course.

Frontend tests:

- Generating state appears while extraction is pending.
- Ready questions render inline with choices.
- Selecting an answer submits once and locks the question.
- Wrong answers reveal the correct choice and explanation immediately.
- Updated concept points are displayed.
- Existing generated quiz history remains separate.

Integration smoke:

- Use a fixture course with one practice section and one answer section.
- Open the chapter test page.
- Trigger lazy extraction.
- Answer one question wrong and verify the score drop appears.
- Refresh and verify the answered state persists.

## Out of Scope For First Implementation

- Full concept dashboard or analytics page.
- Manual instructor review UI for low-confidence extracted questions.
- Retaking inline practice for additional mastery changes.
- Multi-concept weighting for a single question.
- Extracting an entire textbook's answer key upfront.
- Replacing the existing generated chapter quiz deck flow.

## Open Implementation Notes

- The extraction service should be separate from the existing `quiz_generation.py` service because its source-of-truth contract is different: textbook answer key first, generated distractors second.
- The existing job system is the right place for lazy extraction because extraction can be slow and may call an LLM.
- The existing OpenAPI schema generation should be updated after adding backend schemas so the frontend typed client stays aligned.
- The current original-page practice rendering patch should be reviewed during implementation. It can remain as a fallback/source view or be simplified once inline practice assessment is stable.
