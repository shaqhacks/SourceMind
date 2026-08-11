# Test Generation Priority and Lazy Practice Design

Date: 2026-08-10
Status: Approved

## Problem

Opening a chapter-test page currently starts practice-assessment generation for every practice section. Those jobs enter the same durable FIFO queue as an explicitly requested chapter test. The worker executes one job at a time, so a slow Ollama practice call can block the test behind the current job and every previously queued practice job.

Observed evidence:

- Opening one chapter queued ten `generate_practice_assessment` jobs.
- A `qwen3.6:latest` practice call took about 300 seconds and returned only two output tokens, which triggered the structured-output repair path.
- The practice job remained active for more than eleven minutes.
- The later `generate_test` job stayed queued because the worker claims jobs strictly by creation time.

The product behavior is misleading: a student explicitly asks for a test, but the system silently prioritizes background preparation they did not request.

## Goals

- Opening a chapter-test page must be read-only and must not create practice-generation jobs.
- Students can generate practice for one section or explicitly generate all practice for the chapter.
- An explicitly requested chapter test runs before queued practice work.
- Starting a chapter test cancels queued practice jobs for the same chapter and deletes the matching queued `PracticeExtractionRun` rows so later GETs report `not_started` by absence and later POSTs create fresh queued runs/jobs.
- Running and completed practice work is preserved in this version.
- The interface distinguishes queued work from active model thinking.
- Existing streaming and heartbeat behavior remains active after the test reaches execution.
- Duplicate user actions remain idempotent.

## Non-goals

- Running multiple Ollama generation jobs concurrently.
- Preempting or cancelling a practice call that is already running.
- Replacing Ollama, disabling model thinking, or changing the selected model.
- Introducing a general-purpose user-configurable scheduler.
- Optimizing the model's inference speed.

Because running practice is preserved, a test may wait for the single currently active model call. It must not wait behind additional queued practice jobs.

## Architecture

### Lazy practice generation

`InlinePracticeAssessment` continues to fetch existing practice state when it mounts, but a `not_started` response is rendered without sending the start mutation. The section displays a `Generate practice questions` action. The chapter page also displays a `Generate all practice` action that explicitly starts every eligible `not_started` section.

Sections already in `queued`, `generating`, `ready`, or `failed` states retain their existing recovery behavior. Product `not_started` is represented by no `PracticeExtractionRun` for the current fingerprint; cancellation must delete the scoped queued run instead of setting a synthetic run status. Individual and bulk actions use the existing idempotent backend start contract so repeated clicks or overlapping refreshes do not create duplicate extraction runs.

### Central job priority policy

The worker keeps its single-executor model. Job claiming changes from creation-time-only ordering to a centralized, deterministic job-type priority followed by creation time. `generate_test` has higher priority than `generate_practice_assessment`. Jobs of equal priority remain FIFO.

This version does not add a database priority column. The limited type policy belongs beside the worker claim logic so all claim paths use the same ordering and the behavior survives process restarts.

The policy must avoid accidental starvation: only explicitly identified interactive generation types receive elevated priority, and ordering within each class remains FIFO.

### Same-chapter queued-practice cancellation

When a chapter test is requested, the backend resolves the chapter's section IDs and cancels only `queued` `generate_practice_assessment` jobs for those sections. It does not cancel practice jobs from other chapters or courses.

Cancellation and test creation occur in one transaction so the queue cannot be left half-updated. Cancellation first finds candidate queued practice run/job pairs, then uses an atomic conditional `UPDATE jobs ... WHERE id IN (...) AND status = 'queued' RETURNING id`. Only runs whose job IDs are returned are deleted. This prevents stale ORM state from overwriting a job that a worker claimed concurrently. Existing questions and completed runs are untouched. A running practice job is also untouched and is allowed to finish.

The test job is then created through an idempotent generation contract keyed by learner, course, chapter/section scope, and active job status. Repeated requests for the same active scope return the existing queued/running job without duplicate cancellation or duplicate job creation; a later request after a terminal job may create a fresh test job. On the next claim, an active test job wins over lower-priority practice jobs. If a practice job is already running, the test remains visibly queued until that job finishes.

## User experience

### Initial chapter-test view

- Existing ready questions render normally.
- Ungenerated practice sections show source context plus `Generate practice questions`.
- The page offers `Generate all practice` only when at least one eligible section is `not_started`.
- Merely navigating to or refreshing the page performs no generation mutations.

### Generating practice

- An individual action affects only that section.
- `Generate all practice` starts only eligible sections and skips ready, queued, generating, or otherwise non-startable sections. The parent does not POST directly; it sends a per-section start command signal to each eligible child so each `InlinePracticeAssessment` owns its own POST, duplicate guard, state transition, and polling lifecycle.
- Buttons disable while their start request is in flight.
- Existing per-section progress, recovery, and retry behavior remains available.

### Generating a chapter test

- The test request receives an immediate queued acknowledgment.
- The status copy says `Queued` while another model task is active and switches to the streamed thinking/generation message only after execution begins.
- Queued practice cancelled by the request has no run row afterward, returns to the ungenerated state, and can be started later with a fresh run/job.
- The interface does not imply that an active Ollama call can be interrupted in this version.

## Error handling and recovery

- Failure to cancel one of the scoped queued jobs aborts the transaction and prevents test creation, avoiding a partially reordered queue.
- A repeated test request for the same learner/course/chapter/section scope returns the existing queued/running test job rather than creating duplicates or repeating queued-practice cancellation. A new request after the prior scoped job is terminal may create a fresh job.
- A repeated practice request returns the existing active extraction state.
- Restart reconciliation preserves a running practice job according to the existing lease rules, while queued test priority remains deterministic after restart.
- Failed or unavailable Ollama readiness continues to use the existing shared recovery messaging.
- Learner-facing errors do not expose raw provider responses or parser output.

## Verification strategy

### Backend tests

- Worker claims `generate_test` before older queued `generate_practice_assessment` jobs.
- Equal-priority jobs remain FIFO.
- Starting a chapter test cancels only queued practice jobs for that chapter.
- Practice jobs for other chapters and courses are preserved.
- Running and completed practice work is preserved.
- Cancelled practice jobs have progress and lease cleared, and their matching queued practice runs are deleted.
- A subsequent practice POST after cancellation creates a fresh queued `PracticeExtractionRun` and a fresh queued `generate_practice_assessment` job.
- A concurrent worker claim between candidate selection and cancellation is preserved because deletion is limited to job IDs returned by the conditional queued-job update.
- Cancellation and test creation are atomic.
- Restart/reconciliation does not erase the priority guarantee.

### Frontend tests

- Mounting a `not_started` practice section performs a GET but no POST.
- The individual generate action starts only its section and is guarded against duplicate clicks.
- `Generate all practice` starts only eligible sections.
- Queued and actively thinking test states use distinct copy.
- Cancelled queued practice returns to the generate action without an error banner.

### User-perspective E2E

- Opening and refreshing the chapter-test page creates zero new jobs.
- Individual and bulk practice actions create the intended jobs once.
- With older queued practice present, requesting a test cancels same-chapter queued practice and the test becomes the next claimed job after any currently running job.
- The test receives streamed progress once active and completes or surfaces the existing actionable model error state.

## Acceptance criteria

The change is complete when a student can open a chapter test without triggering background generation, explicitly choose practice generation scope, and request a chapter test that does not wait behind queued practice work. All targeted tests, frontend type/lint checks, backend tests, and the relevant E2E flow must pass without modifying the user's dirty `main` checkout.
