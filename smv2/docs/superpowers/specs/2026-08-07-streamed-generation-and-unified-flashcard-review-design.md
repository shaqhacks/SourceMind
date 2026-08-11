# Streamed Generation and Unified Flashcard Review Design

Date: 2026-08-07
Status: Approved visual direction; written specification awaiting user review

## Purpose

SourceMind must support large local thinking models without making generation appear frozen or failing merely because a valid model needs more than two minutes. The flashcard experience must also use one grading model everywhere: learners can grade cards inside a chapter, review every card for a course/subject, repeat missed cards, and reliably return to the review hub. Chapter-test practice extraction must enforce structured model output and recover per section instead of collapsing into repeated opaque failures.

This design combines those requirements because they share the same learner-facing contract: long-running generation creates study material, and the resulting material must remain usable, reviewable, and recoverable from every entry point.

## Confirmed Current Failures

### Ollama generation timeout

- `qwen3.6:latest` is a roughly 24 GB thinking model and was loaded across CPU and GPU.
- The current Ollama adapter sends `stream: false` with a 120-second request timeout.
- Transient retry performs two total attempts, so flashcard and lesson jobs each occupied the single worker for approximately 241 seconds before failing.
- The flashcard and lesson pipelines write `10%` immediately before the blocking provider call and cannot publish further progress while that call is in flight.
- The displayed percentage is therefore a phase marker rather than measurable model completion.

### Chapter-test practice extraction parse failure

- Ten `generate_practice_assessment` jobs completed their Ollama transport calls successfully with `llama3.1:latest`.
- Every result then failed at the first JSON character with `Expecting value: line 1 column 1`.
- The practice-extraction pipeline currently parses once and fails. Unlike flashcard and quiz generation, it has no bounded semantic retry or parse-failure ledger record.
- This is independent of the earlier Qwen timeout: the model returned promptly, but its response did not satisfy the required structured-output contract.

### Review navigation and scope

- The completed review screen links to `/review`, but the same mounted page retains its local `session` phase, so changing only the URL does not reliably return to the hub.
- The current review queue intentionally returns only new or due cards. Its apparent `All` choice means all currently available activities, not every generated card in the course.
- Chapter card browsing reveals answers but does not expose the existing Again/Hard/Good/Easy grading controls.

## Product Decisions

1. Thinking remains enabled for models that support it.
2. Raw model reasoning remains private. It is never rendered to learners, persisted in job progress, logged, or included in exported data.
3. Long-running progress is phase- and time-based, not a fabricated percentage.
4. A healthy stream may run longer than the current 120-second total limit.
5. Every job still has bounded inactivity and wall-clock limits so a broken model cannot monopolize the only worker forever.
6. Course and subject are the same review scope in the current product model. “Review all subject cards” means every generated card in one course, across all its chapters and sections.
7. Again/Hard/Good/Easy always invokes the existing spaced-repetition grading service. Chapter grading is not a disposable self-rating.
8. The chapter test may use all successfully prepared practice material even when some independent practice sections fail. Failed sections remain individually retryable.

## Architecture

### 1. Streaming provider contract

Extend the provider completion contract with optional progress and structured-output inputs rather than making pipelines depend directly on Ollama:

- `progress_callback(event)` receives provider-neutral lifecycle events.
- `response_schema` optionally describes JSON output required by a pipeline.
- `CompletionResult.text` remains the final assembled answer consumed by existing pipelines.
- Anthropic preserves its existing completion behavior while mapping available lifecycle events to the same callback contract.
- Ollama uses `/api/chat` with `stream: true` and consumes newline-delimited JSON until `done`.

Provider lifecycle events are:

- `loading`: connection accepted, awaiting the first model chunk.
- `thinking`: a thinking chunk arrived. The content is discarded immediately.
- `generating`: a final-answer content chunk arrived and was appended.
- `finalizing`: Ollama sent `done`; the pipeline is validating/persisting output.

The provider callback carries only phase, elapsed time, and last-activity time. It must not carry raw thinking or answer text into job progress.

### 2. Timeouts, liveness, and retry

Use distinct timeout concepts:

- Connection timeout: 15 seconds.
- First-activity/model-load timeout: 5 minutes.
- Stream inactivity timeout after first activity: 2 minutes without any valid Ollama chunk.
- Hard wall-clock limit: 30 minutes per provider call.
- Job heartbeat cadence: at most once every 5 seconds.

Any valid thinking, content, or terminal chunk refreshes provider liveness. A throttled job heartbeat updates the phase message, elapsed time, and lease using a separate short database session. The primary pipeline transaction never commits partial model output.

Retry rules:

- One transient retry is allowed only when the failed attempt produced no thinking or content chunks.
- No automatic retry occurs after partial streamed output. Restarting after partial work would duplicate expensive computation and could create ambiguous combined results.
- A model-supplied error chunk fails immediately with a structured `ollama_model_error` category.
- First-activity, inactivity, and wall-clock failures use distinct error detail while sharing the recoverable `ollama_timeout` category.

The single durable worker remains intentional. Running two large local generations concurrently can exceed memory and make both slower. Streaming improves liveness and cancellation without increasing model concurrency.

### 3. Cancellation and background operation

All long-running generation surfaces provide:

- `Continue in background`, which leaves the durable job running and returns the learner to ordinary navigation.
- `Cancel generation`, which marks a cancellation request and closes the active provider stream cooperatively.

Cancellation is terminal and non-retryable unless the learner explicitly starts a new job. Pipelines persist no partial lesson, cards, quiz, or practice questions after cancellation.

### 4. Learner-facing progress

Replace provider-call percentages with honest phases:

- `Waiting for qwen3.6 · 1m 12s`
- `Thinking · 4m 18s`
- `Writing flashcards · 5m 03s`
- `Validating flashcards`

The UI also displays `Model active · latest update 3 seconds ago`. If no update arrives for 30 seconds, copy changes to `Still working · latest model activity 30 seconds ago`; this is not itself a failure. The provider’s inactivity timeout remains authoritative.

SSE stays the browser transport for durable-job status. The server heartbeat renews the job lease and produces status events even when the model is thinking for a long time. A dropped browser connection does not stop the job.

### 5. Structured output for generation pipelines

JSON-producing pipelines supply a JSON schema to the provider. Ollama receives that schema through its structured-output `format` field. The schema must describe the top-level array and required item fields for:

- flashcards;
- quizzes/tests;
- practice-assessment extraction;
- other existing JSON-only generation paths migrated in the same provider boundary.

Pipelines still validate defensively after completion. Provider enforcement is not trusted as the only safety layer.

Semantic retry rules:

- A top-level parse or schema-validation failure gets one repair attempt.
- The repair attempt uses the same response schema and a concise validation error; it does not expose secrets or unrelated prior context.
- Valid individual items may still be filtered according to the current fail-closed domain rules.
- A second invalid response records a `parse_failure` ledger row and fails with a structured, learner-safe message.

Practice extraction adopts the same bounded semantic-retry discipline already used by card and quiz generation. The raw `Expecting value` exception is retained only in internal diagnostics; learners see that the model returned an invalid question format and can retry that section.

## Unified Flashcard Experience

### 1. One grading component

Extract the existing review card interaction into a shared component used by both:

- the `/review` session; and
- chapter/reader flashcard views.

The shared interaction owns:

- front and revealed answer rendering;
- keyboard shortcuts;
- Again/Hard/Good/Easy labels;
- interval previews;
- elapsed-time measurement;
- submitting `POST /api/cards/{card_id}/grade`;
- optimistic advance with explicit rollback/error recovery if grading fails.

The existing scheduling algorithm and review evidence recording remain the source of truth.

### 2. Chapter flashcards

The reader’s chapter flashcard area supports two modes:

- `Browse`: inspect/edit/delete generated cards without changing review scheduling.
- `Review this chapter`: reveal each answer, choose Again/Hard/Good/Easy, and update scheduling exactly like `/review`.

After a chapter review, the learner can review missed cards again, return to the chapter’s card list, or open the subject review hub.

### 3. Subject/course card collection

Add a course-scoped aggregate card query that returns cards across every chapter with chapter/section metadata and learner review state. Supported scopes are:

- `all`: every generated or user-authored card in the course, including cards not currently due;
- `available`: current due and new cards;
- `needs_attention`: cards whose latest grade is Again;
- `chapter`: every card belonging to a selected chapter.

The flashcards page displays total, due, new, needs-attention, and mastered counts. Learners can browse the entire subject, review all, review due, review needs-attention cards, or open a chapter subset. `Review missed` on the session-complete screen is narrower: it uses the exact Again card IDs from that completed session rather than every historical Again card.

Reviewing `all` is an intentional cram session. Grades still update the normal schedule; fetching a not-due card does not itself change scheduling.

### 4. Review-session navigation state

Replace the implicit combination of URL and component-local phase with explicit transition functions:

- `finish session` clears persisted resume state and enters `done`.
- `review missed` creates a fresh session from the completed session’s Again card IDs.
- `back to subject` clears the completed session state, sets the selected course, enters the chooser/subject hub, and updates the URL.
- `all review` clears course/session selection, enters the global hub, and updates the URL.

Navigation buttons perform both the state transition and URL change. A same-page route update is never expected to remount the component.

At completion, the client replaces the active-resume record with a bounded completed-session snapshot containing a generated session ID, course ID, ended time, grade tally, and Again card IDs. The done URL includes that session ID. Refresh may restore that one completed snapshot; starting another session, leaving review, or reaching a 24-hour age limit clears it. This preserves `Review missed` across refresh without introducing a server-side review-session model.

The completion tally remains visible and offers explicit destinations; the ambiguous dead-end `Back to review` link is removed.

## Chapter-Test Practice Material

Each practice section is an independent extraction unit with its own state:

- not started;
- waiting/loading;
- thinking/generating;
- ready;
- failed;
- cancelled.

The chapter-test page summarizes `N of M ready` and renders each section independently. It provides:

- `Retry this section` on one failure;
- `Retry failed only` for all failed sections without duplicating ready/running jobs;
- job details with structured failure category;
- continued access to every ready practice section while others are pending or failed.

The page must not repeatedly start jobs while polling. GET remains read-only for status retrieval; explicit POST actions start or retry extraction. Existing in-flight jobs are rediscovered rather than duplicated.

Transport success followed by invalid JSON is shown as `The model returned an invalid question format`, not as a network or availability failure. Timeout and model errors retain their own recovery guidance.

## API and Data Boundaries

Expected contract changes:

- provider-neutral streamed progress event type;
- optional provider response schema;
- job cancellation endpoint and cancellation state/error detail;
- course card collection endpoint with `all`, `available`, `needs_attention`, and chapter filters;
- review-session requests capable of selecting explicit card IDs or an aggregate scope;
- structured practice-extraction error categories.

No model reasoning text is added to database schemas. No partial generated artifact is persisted. ReviewState and ReviewLog remain authoritative and learner-scoped.

## Error Handling

- Provider errors are categorized before reaching jobs or HTTP responses.
- Retry buttons preserve the learner’s selected course/chapter and scope.
- Grading errors keep the current card visible and prevent silent loss of the learner’s rating.
- Duplicate generation/retry requests reuse or surface the active job instead of creating competing jobs.
- A server restart reconciles streamed jobs through the existing durable-job orphan policy; no partial output is committed.
- A browser refresh rediscovers active generation and active review state.

## Accessibility and Responsive Behavior

- Rating controls remain keyboard accessible with 1–4 shortcuts after answer reveal.
- Phase changes use a polite live region; failures use an alert.
- Elapsed time updates are throttled so screen readers are not interrupted every second.
- Rating meaning never depends on color alone.
- Mobile layouts keep all four grading controls reachable without horizontal scrolling.
- Focus moves to the next card/question or recovery banner after each terminal action.

## Delivery Slices

The implementation is delivered as three sequential, independently verifiable slices rather than one cross-cutting rewrite:

1. **Generation reliability:** provider streaming, private thinking, liveness/timeout/cancellation, structured output, and practice-extraction semantic recovery.
2. **Unified flashcard review:** aggregate course/chapter card queries, shared grading interaction, chapter review, and explicit completed-session navigation.
3. **Chapter-test recovery UX:** per-section status, retry-failed-only behavior, mixed ready/failed rendering, and end-to-end integration with the streamed provider contract.

Each slice must pass its targeted backend/frontend tests before the next begins. The complete build, browser, accessibility, vulnerability, and no-paid-call gates run after all three slices.

## Verification Strategy

### Backend

- Ollama NDJSON parsing for thinking, content, done, malformed, and error chunks.
- Thinking text is never returned, logged, or persisted.
- First-activity, inactivity, hard-limit, cancellation, and retry boundaries.
- No retry after partial stream output.
- Heartbeats renew job leases without committing pipeline data.
- Structured-output request schemas for cards, tests, and practice extraction.
- Practice extraction repairs one invalid response and records parse failure after two.
- Aggregate course/chapter/all/needs-attention card scopes respect learner boundaries.
- Explicit-card review sessions grade through the existing scheduler.

### Frontend

- Phase/elapsed-time progress and background/cancel actions across every generation entry point.
- Direct chapter grading uses the same controls and API behavior as `/review`.
- Subject collection includes not-due cards when `all` is selected.
- Review missed uses only Again cards from the completed-session snapshot, including after refresh.
- Completion actions reach subject and global hubs without remount assumptions.
- Practice sections show mixed ready/running/failed states and retry only failed sections.

### End to end

- Large thinking-model stream runs longer than 120 seconds while remaining visibly alive.
- Simulated silent stream reaches inactivity failure; active stream does not.
- Generated flashcards can be graded in the reader and immediately reflect in review counts.
- A learner can review all cards across several chapters in one subject session.
- Completed-session navigation and missed-card replay work after refresh and direct links.
- Mixed chapter-test extraction results preserve ready practice material and recover failed sections.

## Non-Goals

- Displaying or storing model chain-of-thought.
- Running multiple large Ollama generations concurrently.
- Changing the spaced-repetition scheduling formula.
- Treating arbitrary model output as valid because transport succeeded.
- Replacing durable jobs or SSE with a second job system.
- Making paid-provider calls during verification.

## Acceptance Criteria

1. A healthy thinking-model stream may run for more than 120 seconds without timing out, while the learner sees current phase, elapsed time, and recent activity.
2. No provider call can block forever: first-activity, inactivity, cancellation, and 30-minute hard limits are enforced.
3. Raw reasoning is not visible or persisted.
4. Cards, tests, and practice extraction request and validate structured output; practice extraction gets one bounded repair attempt.
5. Chapter flashcards expose Again/Hard/Good/Easy and grade through the same scheduler as `/review`.
6. Learners can browse and review every card in a course across chapters, including not-due cards when explicitly selecting all.
7. Completed review sessions can replay missed cards or navigate to subject/global hubs without remaining on the completed screen.
8. Chapter-test practice material supports mixed ready/running/failed sections and retry-failed-only behavior.
9. Regression, browser, accessibility, timeout, cancellation, and no-paid-call gates pass before release.
