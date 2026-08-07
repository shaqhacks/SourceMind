# Streamed Generation Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep private model thinking enabled while streaming reliable liveness, enforcing bounded cancellation/timeouts, and producing valid structured study material.

**Architecture:** Extend the existing provider abstraction with provider-neutral progress, cancellation, and response-schema inputs. Ollama consumes NDJSON in an async supervisor running inside the existing worker thread, while the durable job/SSE system receives throttled heartbeats through short database sessions. JSON-producing pipelines pass explicit schemas and retain defensive parse validation plus one bounded repair attempt.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, httpx async streaming, pytest, Next.js 16, React 19, TypeScript, Vitest, Playwright.

## Global Constraints

- Thinking remains enabled for supporting models; raw reasoning is never returned, rendered, logged, persisted, or exported.
- Connection timeout is 15 seconds; first activity is limited to 5 minutes; post-activity silence is limited to 2 minutes; hard wall time is 30 minutes.
- Publish job heartbeats at most once every 5 seconds and never commit partial generated artifacts.
- Allow one transient retry only when an attempt produced no thinking or content chunks.
- Do not retry automatically after partial stream output.
- Keep one durable generation worker; do not add model concurrency.
- Cancellation is cooperative and terminal; explicit restart creates a new job.
- JSON-producing jobs use Ollama structured output and still validate defensively.
- No new runtime dependency is required; use installed `httpx` and Python `asyncio`.
- Every shell command in this workspace is prefixed with `rtk`.
- Verification must not make paid-provider calls.

---

## File Structure

- Create `backend/app/llm/completion_control.py`: provider-neutral progress, cancellation, timeout, and stream-error types.
- Create `backend/app/llm/structured_output.py`: JSON schemas and repair-message helper for JSON generation jobs.
- Create `backend/app/jobs/llm_job_control.py`: bridge provider progress/cancellation to durable job progress and lease renewal.
- Create `backend/app/db/migrations/versions/0023_job_cancellation.py`: add `cancel_requested_at`.
- Create `frontend/components/jobs/GenerationProgress.tsx`: shared phase/elapsed/cancel UI.
- Modify existing provider, job, pipeline, generated API, and generation-entry components listed per task below.

### Task 1: Lock the Provider-Neutral Completion Contract

**Files:**
- Create: `backend/app/llm/completion_control.py`
- Modify: `backend/app/llm/provider.py`
- Modify: `backend/app/llm/retry.py`
- Modify: `backend/app/llm/anthropic_provider.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_llm_provider.py`

**Interfaces:**
- Produces: `CompletionPhase`, `CompletionProgress`, `CompletionOptions`, `ProviderStreamError`, `ProviderCancelledError`.
- Produces: an optional `options: CompletionOptions | None = None` keyword on `Provider.complete()` and a required `options: CompletionOptions` keyword on `_complete_impl()`.
- Consumed by: Tasks 2, 4, and 5.

- [ ] **Step 1: Write failing contract tests**

Add tests proving the base provider passes an immutable options object into concrete providers and that a partial-stream error is not retried:

```python
def test_complete_passes_progress_schema_and_cancel_controls(stub_provider):
    seen = []
    options = CompletionOptions(
        progress=lambda event: seen.append(event.phase),
        is_cancelled=lambda: False,
        response_schema={"type": "array"},
    )
    stub_provider.complete(
        [{"role": "user", "content": "hello"}],
        max_tokens=8,
        purpose="cards",
        options=options,
    )
    assert stub_provider.received_completion_options[-1] is options


def test_partial_stream_error_is_not_retried(stub_provider):
    stub_provider.exceptions = [
        ProviderStreamError("stream stopped", category="ollama_inactivity_timeout", had_activity=True)
    ]
    with pytest.raises(ProviderStreamError):
        stub_provider.complete([{"role": "user", "content": "x"}], max_tokens=8, purpose="cards")
    assert stub_provider.complete_call_count == 1
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
rtk uv run pytest -q backend/tests/test_llm_provider.py -k 'completion_options or partial_stream'
```

Expected: FAIL because the new types/signatures do not exist.

- [ ] **Step 3: Define the completion-control types and retry boundary**

Implement these exact public shapes in `completion_control.py`:

```python
CompletionPhase = Literal["loading", "thinking", "generating", "finalizing"]

@dataclass(frozen=True)
class CompletionProgress:
    phase: CompletionPhase
    elapsed_seconds: float
    seconds_since_activity: float

@dataclass(frozen=True)
class CompletionOptions:
    progress: Callable[[CompletionProgress], None] | None = None
    is_cancelled: Callable[[], bool] | None = None
    response_schema: dict[str, Any] | None = None

class ProviderStreamError(Exception):
    def __init__(self, message: str, *, category: str, had_activity: bool):
        super().__init__(message)
        self.category = category
        self.had_activity = had_activity

class ProviderCancelledError(Exception):
    pass
```

Extend `retry.py`’s private `_is_transient()` classifier to recognize `ProviderStreamError` only when `had_activity` is false and `category` is one of `ollama_connect_error`, `ollama_first_activity_timeout`, or `ollama_transport_error`. It must return false for inactivity after activity, hard-wall timeout after activity, model error chunks, malformed chunks, and cancellation. Keep `retry_transient(fn)` and all existing Anthropic/httpx behavior unchanged so the provider continues to use one retry boundary. Update Anthropic and the shared stub to accept `CompletionOptions`; Anthropic may ignore `response_schema` in this slice but must emit `loading` then `finalizing` when a callback exists.

- [ ] **Step 4: Run provider tests**

Run:

```bash
rtk uv run pytest -q backend/tests/test_llm_provider.py backend/tests/test_llm_retry.py
```

Expected: PASS, including existing ledger behavior.

- [ ] **Step 5: Commit the contract**

```bash
rtk git add backend/app/llm/completion_control.py backend/app/llm/provider.py backend/app/llm/retry.py backend/app/llm/anthropic_provider.py backend/tests/conftest.py backend/tests/test_llm_provider.py backend/tests/test_llm_retry.py
rtk git commit -m "feat(llm): define streamed completion controls"
```

### Task 2: Stream Ollama Thinking and Content Safely

**Files:**
- Modify: `backend/app/llm/ollama_provider.py`
- Create: `backend/tests/test_ollama_streaming.py`
- Modify: `backend/tests/test_llm_provider.py`

**Interfaces:**
- Consumes: `CompletionOptions`, `CompletionProgress`, `ProviderStreamError`, `ProviderCancelledError` from Task 1.
- Produces: an Ollama `_complete_impl()` that assembles only `message.content`, discards `message.thinking`, and returns the existing `CompletionResult`.
- Consumed by: every generation pipeline through `Provider.complete()`.

- [ ] **Step 1: Write failing NDJSON and privacy tests**

Use `httpx.MockTransport` with an `AsyncByteStream` fixture and assert the request contains `stream: true` and the optional JSON schema:

```python
@pytest.mark.parametrize("thinking", ["private reasoning", ""])
def test_ollama_stream_discards_thinking_and_assembles_content(monkeypatch, thinking):
    lines = [
        {"message": {"thinking": thinking, "content": ""}, "done": False},
        {"message": {"thinking": "", "content": "["}, "done": False},
        {"message": {"thinking": "", "content": "]"}, "done": False},
        {"message": {"content": ""}, "done": True, "prompt_eval_count": 5, "eval_count": 2},
    ]
    result, captured, phases = run_fake_ollama_stream(monkeypatch, lines)
    assert result.text == "[]"
    assert thinking not in result.text
    assert captured["stream"] is True
    assert phases == ["loading", "thinking", "generating", "finalizing"]
```

Add separate tests for malformed lines, an Ollama error chunk such as `{ "error": "model runner stopped" }`, cancellation while waiting, first-activity timeout, inactivity after activity, and the 30-minute hard deadline using injected clock/deadline constants rather than real sleeps.

- [ ] **Step 2: Run the new suite and confirm failure**

```bash
rtk uv run pytest -q backend/tests/test_ollama_streaming.py
```

Expected: FAIL because Ollama still uses one non-streaming `httpx.post()`.

- [ ] **Step 3: Implement the async stream supervisor**

Replace `_REQUEST_TIMEOUT_SECONDS` with named constants and a private coroutine:

```python
_CONNECT_TIMEOUT_SECONDS = 15.0
_FIRST_ACTIVITY_TIMEOUT_SECONDS = 300.0
_INACTIVITY_TIMEOUT_SECONDS = 120.0
_HARD_TIMEOUT_SECONDS = 1800.0
_SUPERVISOR_TICK_SECONDS = 5.0
```

Implement `_complete_stream(self, messages: list[dict], *, max_tokens: int, options: CompletionOptions) -> CompletionResult` as a private coroutine. Create one pending `anext(response.aiter_lines())` task and supervise it with `asyncio.wait({pending_line}, timeout=_SUPERVISOR_TICK_SECONDS)`. On each tick, check cancellation and deadlines without cancelling a healthy pending read. Parse each line independently, discard `message.thinking`, append only `message.content`, collect usage from the terminal chunk, and emit deduplicated phase callbacks. `_complete_impl()` calls `asyncio.run(self._complete_stream(messages, max_tokens=max_tokens, options=options))`; worker and FastAPI sync call sites already execute outside the application event loop.

- [ ] **Step 4: Verify Ollama and provider regressions**

```bash
rtk uv run pytest -q backend/tests/test_ollama_streaming.py backend/tests/test_llm_provider.py backend/tests/test_llm_status.py
```

Expected: PASS with no raw thinking text in assertions, logs, or returned results.

- [ ] **Step 5: Commit Ollama streaming**

```bash
rtk git add backend/app/llm/ollama_provider.py backend/tests/test_ollama_streaming.py backend/tests/test_llm_provider.py
rtk git commit -m "feat(ollama): stream private thinking completions"
```

### Task 3: Add Durable Cooperative Job Cancellation

**Files:**
- Create: `backend/app/db/migrations/versions/0023_job_cancellation.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/jobs_service.py`
- Modify: `backend/app/routers/jobs.py`
- Modify: `backend/app/jobs/worker.py`
- Modify: `backend/tests/test_jobs_api.py`
- Modify: `backend/tests/test_sse_job_events.py`
- Modify: `backend/tests/test_reconciler.py`
- Create: `backend/tests/test_job_cancellation_migration.py`

**Interfaces:**
- Produces: `Job.cancel_requested_at: datetime | None`.
- Produces: `POST /api/jobs/{job_id}/cancel` returning `JobOut`.
- Produces: `jobs_service.is_cancel_requested(job_id) -> bool`.
- Extends terminal statuses with `cancelled`.
- Extends the job event stream lifetime to 1,860 seconds so the 30-minute provider hard deadline and final terminal event fit inside one connection.
- Consumed by: Task 4 and frontend Task 6.

- [ ] **Step 1: Write failing cancellation lifecycle tests**

Add API and worker tests for queued and running jobs:

```python
def test_cancel_queued_job_is_immediately_terminal(client):
    job = client.post("/api/jobs", json={"type": "noop", "payload": {}}).json()
    response = client.post(f"/api/jobs/{job['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["retryable"] is False
    assert run_due_jobs_once() is False


def test_cancel_running_job_sets_cooperative_request(client, running_job):
    response = client.post(f"/api/jobs/{running_job.id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["cancel_requested_at"] is not None
    assert jobs_service.is_cancel_requested(running_job.id) is True
```

Assert SSE emits and closes on `cancelled`, `POST /api/jobs/{id}/retry` rejects cancelled jobs, and orphan reconciliation treats a cancel-requested expired job as cancelled rather than requeued. A learner who wants to run the operation again uses the existing domain generation action, which creates a fresh job.

- [ ] **Step 2: Run cancellation tests and confirm failure**

```bash
rtk uv run pytest -q backend/tests/test_jobs_api.py backend/tests/test_sse_job_events.py backend/tests/test_reconciler.py -k cancel
```

Expected: FAIL because the column, endpoint, and status do not exist.

- [ ] **Step 3: Implement migration, service transition, and worker handling**

Migration shape:

```python
def upgrade() -> None:
    op.add_column("jobs", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))

def downgrade() -> None:
    op.drop_column("jobs", "cancel_requested_at")
```

Service rules:

```python
def cancel_job(job_id: str) -> Job:
    # queued -> cancelled immediately
    # running -> retain running, set cancel_requested_at
    # terminal -> idempotently return unchanged
```

Add `cancelled` to backend terminal sets and error-envelope handling, expose `cancel_requested_at` through `JobOut`, make `JobOut.retryable` false when status is cancelled, reject cancelled jobs in the generic retry service, and raise the SSE loop ceiling from 600 to 1,860 seconds. In `execute_job()`, catch `ProviderCancelledError`, roll back pipeline data, then persist `status="cancelled"`, `error=None`, `lease_until=None`. Never mark cancellation as failure.

- [ ] **Step 4: Run migration/job/SSE tests**

```bash
rtk uv run pytest -q backend/tests/test_job_cancellation_migration.py backend/tests/test_jobs_api.py backend/tests/test_sse_job_events.py backend/tests/test_reconciler.py backend/tests/test_worker_claim.py
```

Expected: PASS; cancelled jobs are never claimed or orphan-requeued.

- [ ] **Step 5: Commit cancellation**

```bash
rtk git add backend/app/db/migrations/versions/0023_job_cancellation.py backend/app/db/models.py backend/app/schemas.py backend/app/services/jobs_service.py backend/app/routers/jobs.py backend/app/jobs/worker.py backend/tests/test_job_cancellation_migration.py backend/tests/test_jobs_api.py backend/tests/test_sse_job_events.py backend/tests/test_reconciler.py
rtk git commit -m "feat(jobs): add cooperative generation cancellation"
```

### Task 4: Bridge Provider Activity into Job Heartbeats

**Files:**
- Create: `backend/app/jobs/llm_job_control.py`
- Modify: `backend/app/pipeline/cards_generation.py`
- Modify: `backend/app/pipeline/generation.py`
- Modify: `backend/app/pipeline/quiz_generation.py`
- Modify: `backend/app/pipeline/practice_extraction.py`
- Modify: `backend/app/pipeline/concept_extraction.py`
- Modify: `backend/app/pipeline/concept_practice_generation.py`
- Modify: `backend/tests/test_job_progress.py`
- Modify: `backend/tests/test_cards_generation.py`
- Modify: `backend/tests/test_lesson_generation.py`

**Interfaces:**
- Consumes: `CompletionOptions` and `jobs_service.is_cancel_requested()`.
- Produces: `completion_options_for_job(job_id: str, *, artifact: str, response_schema: dict | None = None) -> CompletionOptions`.
- Produces progress dictionaries with `stage`, `pct=None`, `message`, `elapsed_seconds`, and `last_activity_seconds`.

- [ ] **Step 1: Write failing heartbeat/privacy tests**

```python
def test_job_completion_control_throttles_and_renews_lease(client, monkeypatch):
    options = completion_options_for_job("job-1", artifact="flashcards")
    options.progress(CompletionProgress("thinking", 65.0, 0.0))
    options.progress(CompletionProgress("thinking", 66.0, 1.0))
    assert progress_write_count() == 1
    assert get_job("job-1").progress == {
        "stage": "thinking",
        "pct": None,
        "message": "Thinking · 1m 05s",
        "elapsed_seconds": 65,
        "last_activity_seconds": 0,
    }
```

Add a test using a sentinel reasoning string and assert it is absent from serialized progress and captured logs. Add a cancellation-check test that reads the committed flag through a separate session.

- [ ] **Step 2: Run focused heartbeat tests and confirm failure**

```bash
rtk uv run pytest -q backend/tests/test_job_progress.py -k 'completion_control or private or cancel'
```

Expected: FAIL because the bridge does not exist.

- [ ] **Step 3: Implement the throttled bridge and wire every LLM job**

`completion_options_for_job()` maps phases to artifact-aware learner copy and calls existing `job_progress()` at most once per five seconds or immediately on phase change. It uses `jobs_service.is_cancel_requested` for cooperative cancellation. Replace each pipeline’s pre-call fake `10%` state with `loading` and pass the returned options into every `provider.complete()` call, including semantic retries.

Change `job_progress()` to accept `pct: float | None` plus optional `elapsed_seconds` and `last_activity_seconds` keywords, and persist those values in the existing progress dictionary. Keep existing numeric-percentage callers backward compatible. The bridge opens and closes a short independent session for each throttled write so provider heartbeats never commit the pipeline transaction.

Do not route embedding calls through this completion bridge; embedding already has its own bounded item progress.

- [ ] **Step 4: Run all generation pipeline tests**

```bash
rtk uv run pytest -q backend/tests/test_job_progress.py backend/tests/test_cards_generation.py backend/tests/test_lesson_generation.py backend/tests/test_quiz.py backend/tests/test_practice_extraction.py backend/tests/test_concept_practice_generation.py
```

Expected: PASS with phase-based progress and unchanged successful artifacts.

- [ ] **Step 5: Commit job heartbeats**

```bash
rtk git add backend/app/jobs/llm_job_control.py backend/app/pipeline/cards_generation.py backend/app/pipeline/generation.py backend/app/pipeline/quiz_generation.py backend/app/pipeline/practice_extraction.py backend/app/pipeline/concept_extraction.py backend/app/pipeline/concept_practice_generation.py backend/tests/test_job_progress.py backend/tests/test_cards_generation.py backend/tests/test_lesson_generation.py
rtk git commit -m "feat(jobs): publish streamed model heartbeats"
```

### Task 5: Enforce Structured Output and Repair Practice Extraction

**Files:**
- Create: `backend/app/llm/structured_output.py`
- Modify: `backend/app/jobs/worker.py`
- Modify: `backend/app/pipeline/cards_generation.py`
- Modify: `backend/app/pipeline/quiz_generation.py`
- Modify: `backend/app/pipeline/practice_extraction.py`
- Modify: `backend/app/pipeline/concept_extraction.py`
- Modify: `backend/app/pipeline/concept_practice_generation.py`
- Modify: `backend/tests/test_cards_generation.py`
- Modify: `backend/tests/test_quiz.py`
- Modify: `backend/tests/test_practice_extraction.py`
- Modify: `backend/tests/test_concept_extraction.py`
- Modify: `backend/tests/test_concept_practice_generation.py`
- Modify: `backend/tests/test_job_progress.py`

**Interfaces:**
- Produces constants `CARDS_SCHEMA`, `QUIZ_SCHEMA`, `PRACTICE_ASSESSMENT_SCHEMA`, `CURRICULUM_SCHEMA`, and `CONCEPT_PRACTICE_SCHEMA`.
- Produces `repair_messages(messages, validation_error) -> list[dict]` that adds a concise format correction without secrets.
- Produces `InvalidModelOutputError`, carrying only a learner-safe `error_detail` envelope.
- Consumed through Task 1’s `CompletionOptions.response_schema`.

- [ ] **Step 1: Write failing schema and semantic-repair tests**

For practice extraction, reproduce the observed transport-success/empty-content failure:

```python
def test_practice_extraction_repairs_one_invalid_response(client, ingest_course, stub_provider):
    stub_provider.responses = ["", valid_practice_json()]
    job_id = start_practice_job(client, ingest_course)
    run_due_jobs_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert stub_provider.complete_call_count == 2
    assert stub_provider.received_completion_options[0].response_schema == PRACTICE_ASSESSMENT_SCHEMA


def test_practice_extraction_records_parse_failure_after_two_invalid_responses(
    client, ingest_course, stub_provider
):
    stub_provider.responses = ["", "not json"]
    job_id = start_practice_job(client, ingest_course)
    run_due_jobs_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert [row.status for row in recent_calls()] == ["ok", "ok", "parse_failure"]
    assert job["error_detail"]["code"] == "invalid_model_output"
```

Add shape tests asserting every required parser field appears in its schema and that unknown claim IDs still fail closed.

- [ ] **Step 2: Run structured-output tests and confirm failure**

```bash
rtk uv run pytest -q backend/tests/test_cards_generation.py backend/tests/test_quiz.py backend/tests/test_practice_extraction.py backend/tests/test_concept_extraction.py backend/tests/test_concept_practice_generation.py -k 'schema or repair or parse_failure'
```

Expected: practice repair/schema assertions FAIL.

- [ ] **Step 3: Implement schemas and consistent two-attempt semantic parsing**

Pass the appropriate schema on the first completion and repair completion. Preserve the current per-item fail-closed validation. On the second top-level failure, record exactly one semantic `parse_failure` ledger row and raise `InvalidModelOutputError` with this learner-safe detail:

```python
{
    "code": "invalid_model_output",
    "message": "The model returned an invalid question format.",
    "failure_category": "structured_output_invalid",
}
```

Keep raw JSON exception text in server diagnostics only.

Modify `backend/app/jobs/worker.py` so `execute_job()` catches `InvalidModelOutputError` before the generic exception handler and persists its `error_detail` unchanged while setting the normal failed terminal state. Add a worker assertion to `backend/tests/test_job_progress.py` proving the public error excludes raw model text.

- [ ] **Step 4: Run all structured generation tests**

```bash
rtk uv run pytest -q backend/tests/test_cards_generation.py backend/tests/test_quiz.py backend/tests/test_practice_extraction.py backend/tests/test_concept_extraction.py backend/tests/test_concept_practice_generation.py backend/tests/test_llm_provider.py
```

Expected: PASS, including prior dedupe and claim-validation tests.

- [ ] **Step 5: Commit structured generation**

```bash
rtk git add backend/app/llm/structured_output.py backend/app/jobs/worker.py backend/app/pipeline/cards_generation.py backend/app/pipeline/quiz_generation.py backend/app/pipeline/practice_extraction.py backend/app/pipeline/concept_extraction.py backend/app/pipeline/concept_practice_generation.py backend/tests/test_cards_generation.py backend/tests/test_quiz.py backend/tests/test_practice_extraction.py backend/tests/test_concept_extraction.py backend/tests/test_concept_practice_generation.py backend/tests/test_job_progress.py
rtk git commit -m "fix(llm): enforce structured study material"
```

### Task 6: Add Shared Streaming Progress and Cancellation UI

**Files:**
- Create: `frontend/components/jobs/GenerationProgress.tsx`
- Create: `frontend/__tests__/generation-progress.test.tsx`
- Modify: `frontend/lib/api/client.ts`
- Modify: `frontend/lib/hooks/useJobEvents.ts`
- Modify: `frontend/lib/jobs/format.ts`
- Modify: `frontend/components/reader/CardsCTA.tsx`
- Modify: `frontend/components/reader/LessonPane.tsx`
- Modify: `frontend/components/reader/QuizzesPanel.tsx`
- Modify: `frontend/components/reader/GenerateAllLessons.tsx`
- Modify: `frontend/components/flashcards/ChapterDeckCard.tsx`
- Modify: `frontend/components/tests/GenerateTestCard.tsx`
- Modify: `frontend/components/chapter/ChapterTestClient.tsx`
- Modify: `frontend/__tests__/use-job-events.test.ts`
- Modify: `frontend/__tests__/cards-cta.test.tsx`
- Modify: `frontend/__tests__/lesson-pane.test.tsx`

**Interfaces:**
- Consumes generated `JobOut.cancel_requested_at`, `cancelled` status, and `POST /api/jobs/{id}/cancel`.
- Produces `GenerationProgress({ job, quiet, onCancel, onContinue })`.
- Produces phase copy with elapsed and recent-activity text; never accepts reasoning text.

- [ ] **Step 1: Write failing component and hook tests**

```tsx
it("shows private thinking liveness without a fake percentage", async () => {
  render(<GenerationProgress job={thinkingJob({ elapsed_seconds: 258 })} quiet={false} />);
  expect(screen.getByText("Thinking · 4m 18s")).toBeInTheDocument();
  expect(screen.getByText(/model active/i)).toBeInTheDocument();
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
});

it("treats cancelled as terminal and closes EventSource", async () => {
  const { result } = renderHook(() => useJobEvents("job-1"));
  FakeEventSource.instances[0].emit("update", { id: "job-1", status: "cancelled", progress: null });
  expect(result.current.done).toBe(true);
  expect(FakeEventSource.instances[0].closed).toBe(true);
});
```

Test Cancel calls the API once, Continue in background invokes navigation callback without cancelling, quiet copy appears after 30 seconds, and controls remain keyboard reachable.

- [ ] **Step 2: Run frontend tests and confirm failure**

```bash
rtk npm --prefix frontend test -- --run __tests__/generation-progress.test.tsx __tests__/use-job-events.test.ts
```

Expected: FAIL because the component and cancelled contract do not exist.

- [ ] **Step 3: Implement the shared progress surface and replace duplicated status lines**

Add `cancelJob(jobId)` to the client, include `cancelled` in terminal statuses, and make `GenerationProgress` the only long-running generation renderer. Its public props are:

```tsx
interface GenerationProgressProps {
  job: JobEvent | null;
  quiet: boolean;
  onCancel?: () => Promise<void>;
  onContinue?: () => void;
  compact?: boolean;
}
```

Use polite live-region updates only on phase changes; update visible elapsed time without re-announcing every tick. Preserve each surface’s existing RecoveryBanner behavior after failure.

- [ ] **Step 4: Regenerate API artifacts and run frontend gates**

```bash
rtk uv run python -m app.export_openapi ../openapi.json
rtk npm --prefix frontend run gen:api
rtk npm --prefix frontend run typecheck
rtk npm --prefix frontend test -- --run
rtk npm --prefix frontend run lint
```

Run the OpenAPI command with `backend` as the working directory and the npm commands from the repository root. Expected: generated files have intentional cancellation-contract changes only; all tests pass.

- [ ] **Step 5: Commit the frontend progress contract**

```bash
rtk git add openapi.json frontend/lib/api/schema.d.ts frontend/lib/api/client.ts frontend/lib/hooks/useJobEvents.ts frontend/lib/jobs/format.ts frontend/components/jobs/GenerationProgress.tsx frontend/components/reader/CardsCTA.tsx frontend/components/reader/LessonPane.tsx frontend/components/reader/QuizzesPanel.tsx frontend/components/reader/GenerateAllLessons.tsx frontend/components/flashcards/ChapterDeckCard.tsx frontend/components/tests/GenerateTestCard.tsx frontend/components/chapter/ChapterTestClient.tsx frontend/__tests__/generation-progress.test.tsx frontend/__tests__/use-job-events.test.ts frontend/__tests__/cards-cta.test.tsx frontend/__tests__/lesson-pane.test.tsx
rtk git commit -m "feat(ui): stream generation liveness and cancellation"
```

### Task 7: Prove the Complete Generation Reliability Slice

**Files:**
- Create: `frontend/e2e/generation-streaming.spec.ts`
- Modify: `frontend/playwright.config.ts` only if the test needs an explicit local fake-Ollama process fixture.
- Modify: `ultraqa-comprehensive-feature-audit/report.md`

**Interfaces:**
- Consumes every contract from Tasks 1–6.
- Produces final evidence that healthy streams exceed 120 seconds in simulated time, cancellation is terminal, structured recovery works, and no paid calls occur.

- [ ] **Step 1: Add browser scenarios using mocked job/SSE responses**

Cover these exact scenarios:

```ts
test("thinking remains active beyond the old timeout and can continue in background", async ({ page }) => {
  await installGenerationRoutes(page, { phases: ["loading", "thinking"], elapsedSeconds: 125 });
  await expectThinkingLivenessAndBackgroundAction(page);
});
test("cancelled generation becomes terminal without a failure banner", async ({ page }) => {
  await installGenerationRoutes(page, { phases: ["thinking", "cancelled"], cancelAccepted: true });
  await expectCancellationWithoutFailure(page);
});
test("invalid practice output surfaces structured retry guidance", async ({ page }) => {
  await installPracticeFailureRoute(page, { code: "invalid_model_output" });
  await expectStructuredRetryGuidance(page);
});
```

Do not wait 120 real seconds; use deterministic backend unit tests for timing and browser route interception for UI state.

- [ ] **Step 2: Run the targeted slice three times**

```bash
rtk uv run pytest -q backend/tests/test_ollama_streaming.py backend/tests/test_job_progress.py backend/tests/test_jobs_api.py backend/tests/test_sse_job_events.py backend/tests/test_cards_generation.py backend/tests/test_lesson_generation.py backend/tests/test_quiz.py backend/tests/test_practice_extraction.py
rtk uv run pytest -q backend/tests/test_ollama_streaming.py backend/tests/test_job_progress.py backend/tests/test_jobs_api.py backend/tests/test_sse_job_events.py backend/tests/test_cards_generation.py backend/tests/test_lesson_generation.py backend/tests/test_quiz.py backend/tests/test_practice_extraction.py
rtk uv run pytest -q backend/tests/test_ollama_streaming.py backend/tests/test_job_progress.py backend/tests/test_jobs_api.py backend/tests/test_sse_job_events.py backend/tests/test_cards_generation.py backend/tests/test_lesson_generation.py backend/tests/test_quiz.py backend/tests/test_practice_extraction.py
```

Expected: all three runs pass without timing flakiness.

- [ ] **Step 3: Run frontend and browser verification**

```bash
rtk npm --prefix frontend run typecheck
rtk npm --prefix frontend run lint
rtk npm --prefix frontend test -- --run
rtk npm --prefix frontend run test:e2e -- generation-streaming.spec.ts
```

Expected: PASS with no critical accessibility violations.

- [ ] **Step 4: Run the repository release gate and vulnerability scans**

```bash
rtk ./build.sh
rtk npm --prefix frontend audit --audit-level=high --cache /private/tmp/npm-cache
rtk npm --prefix frontend audit --omit=dev --audit-level=high --cache /private/tmp/npm-cache
rtk uvx pip-audit
```

Expected: `BUILD OK`, zero npm vulnerabilities, and no known Python vulnerabilities.

- [ ] **Step 5: Record evidence and commit the completed slice**

Update the QA report with exact counts, timing simulations, cancellation behavior, structured-output recovery, and confirmation that no paid provider was called.

```bash
rtk git add frontend/e2e/generation-streaming.spec.ts ultraqa-comprehensive-feature-audit/report.md
rtk git commit -m "test(e2e): verify streamed generation reliability"
```
