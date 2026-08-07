# Chapter-Test Practice Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Complete Tasks 1–5 of `docs/superpowers/plans/2026-08-07-streamed-generation-reliability.md` before starting this plan.

**Goal:** Make chapter-test practice material resilient when some section extractions are slow or invalid, with truthful per-section status, one-click retry of failed sections only, and uninterrupted access to ready questions and textbook pages.

**Architecture:** Keep the existing section-isolated practice lifecycle and explicit GET/POST semantics. Expose the job’s learner-safe structured error through the practice assessment response, let each inline assessment report a small status contract upward, and derive the chapter aggregate entirely in `ChapterTestClient`. Retrying increments only failed children’s retry versions, so ready and active sections are never restarted.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, pytest, Next.js 16, React 19, TypeScript, Vitest, Playwright.

## Global Constraints

- Dependency: streamed generation plan Tasks 1–5 must already provide structured Ollama output, one repair attempt, private liveness, and `invalid_model_output` errors.
- A read-only GET must never create or restart a practice extraction job.
- Initial `not_started` sections may auto-start once through the existing POST behavior.
- “Retry failed” must POST only sections currently reported failed; ready and generating sections are untouched.
- Repeated clicks or rerenders must not create duplicate active jobs.
- Ready questions and textbook source remain usable while siblings load or fail.
- The chapter-test generation action remains independent from practice extraction state.
- Learner-facing UI shows safe error category/remediation only, never raw model output or parser text.
- Parent aggregation has four states: `loading`, `generating`, `ready`, `failed`.
- No new runtime dependency is required.
- Every shell command in this workspace is prefixed with `rtk`.

---

## File Structure

- Create `frontend/components/chapter/practiceAssessmentState.ts`: shared child-to-parent state types and aggregate helper.
- Create `frontend/e2e/chapter-test-practice-recovery.spec.ts`: mixed-state, selective retry, and degraded-mode browser coverage.
- Modify the existing practice schema/service, generated client, inline assessment, chapter test, and tests listed per task below.

### Task 1: Expose Learner-Safe Practice Failure Details

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/practice_service.py`
- Modify: `backend/tests/test_practice_service.py`
- Modify: `backend/tests/test_practice_api.py`

**Interfaces:**
- Extends `PracticeAssessmentOut` with `error_detail: dict[str, Any] | None = None`.
- Failed responses decode the linked job’s existing error envelope through `decode_job_error()`.
- Generic historical failures retain the current message and return `error_detail=None`.

- [ ] **Step 1: Write failing service and API tests**

```python
def test_failed_practice_assessment_exposes_safe_structured_job_error(client, failed_practice_run):
    failed_practice_run.job.error = encode_job_error(
        "The model returned an invalid question format.",
        {
            "code": "invalid_model_output",
            "message": "The model returned an invalid question format.",
            "failure_category": "structured_output_invalid",
        },
    )
    response = client.get(failed_practice_run.url)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_detail"]["code"] == "invalid_model_output"
    assert "Expecting value" not in response.text


def test_legacy_failed_practice_assessment_has_no_structured_detail(client, legacy_failed_run):
    response = client.get(legacy_failed_run.url)
    assert response.status_code == 200
    assert response.json()["message"] == "Practice question extraction failed."
    assert response.json()["error_detail"] is None
```

Also assert ready, generating, and not-started responses contain `error_detail: null`.

- [ ] **Step 2: Run focused backend tests and confirm failure**

```bash
rtk uv run pytest -q backend/tests/test_practice_service.py backend/tests/test_practice_api.py -k error_detail
```

Expected: FAIL because the practice response drops the job envelope.

- [ ] **Step 3: Decode only the existing safe envelope**

Add `error_detail` to every practice response shape. Change `_run_response()` to accept the already-loaded `Job | None`; when the job is failed, call `decode_job_error(job.error)` and return the decoded detail only when it is a dictionary. Do not synthesize raw exception text into `error_detail`, and do not expose `PracticeExtractionRun.error`.

- [ ] **Step 4: Run practice backend regressions**

```bash
rtk uv run pytest -q backend/tests/test_practice_service.py backend/tests/test_practice_api.py backend/tests/test_practice_extraction.py
```

Expected: PASS, including read-only GET and retry idempotency tests.

- [ ] **Step 5: Commit safe error details**

```bash
rtk git add backend/app/schemas.py backend/app/services/practice_service.py backend/tests/test_practice_service.py backend/tests/test_practice_api.py
rtk git commit -m "fix(practice): expose safe extraction failures"
```

### Task 2: Define and Test the Per-Section Status Contract

**Files:**
- Create: `frontend/components/chapter/practiceAssessmentState.ts`
- Create: `frontend/__tests__/practice-assessment-state.test.ts`
- Modify: `frontend/components/chapter/InlinePracticeAssessment.tsx`
- Modify: `frontend/__tests__/inline-practice-assessment.test.tsx`

**Interfaces:**
- Produces `PracticeSectionState` with `kind`, `sectionId`, `questionCount`, `message`, `errorDetail`, and `retryKind`.
- Adds optional `onStateChange(state: PracticeSectionState): void` to `InlinePracticeAssessment`.
- Adds `retryVersion: number` to `InlinePracticeAssessment`; a higher value retries only the child’s current failure mode.

- [ ] **Step 1: Write failing child-state tests**

```tsx
it("reports generating and ready transitions to its parent", async () => {
  mockedGetPracticeAssessment
    .mockResolvedValueOnce(ok(makeAssessment({ status: "generating", questions: [] })))
    .mockResolvedValueOnce(ok(makeAssessment({ status: "ready", questions: [makeQuestion()] })));
  render(
    <InlinePracticeAssessment
      courseId="course-1"
      sectionId="section-1"
      retryVersion={0}
      onStateChange={onStateChange}
    />,
  );
  await advancePracticePoll();
  expect(onStateChange).toHaveBeenCalledWith(
    expect.objectContaining({ kind: "generating", sectionId: "section-1" }),
  );
  expect(onStateChange).toHaveBeenCalledWith(
    expect.objectContaining({ kind: "ready", sectionId: "section-1", questionCount: 1 }),
  );
});

it("retries a failed extraction once when retryVersion increases", async () => {
  mockedGetPracticeAssessment.mockResolvedValue(
    ok(makeAssessment({ status: "failed", questions: [], message: "Invalid format" })),
  );
  const view = renderPracticeChild({ retryVersion: 0 });
  await screen.findByText("Invalid format");
  view.rerender(practiceChild({ retryVersion: 1 }));
  await waitFor(() => expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1));
});
```

Add tests proving an unchanged retry version does nothing, a version increase while ready or generating does nothing, a load transport failure reports `retryKind: "reload"`, an extraction failure reports `retryKind: "restart"`, and unmount/stale responses do not notify the parent.

- [ ] **Step 2: Run inline tests and confirm failure**

```bash
rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/inline-practice-assessment.test.tsx
```

Expected: FAIL because the child has no status callback or external retry signal.

- [ ] **Step 3: Implement transition reporting without render side effects**

Define these exact state kinds:

```ts
export type PracticeSectionState =
  | { kind: "loading"; sectionId: string; questionCount: 0; message: null; errorDetail: null; retryKind: null }
  | { kind: "generating"; sectionId: string; questionCount: 0; message: string | null; errorDetail: null; retryKind: null }
  | { kind: "ready"; sectionId: string; questionCount: number; message: null; errorDetail: null; retryKind: null }
  | { kind: "failed"; sectionId: string; questionCount: 0; message: string; errorDetail: ApiErrorDetail | null; retryKind: "reload" | "restart" };
```

Notify from the same async transition handlers that update local state, not during render. Store the last emitted state signature in a ref so polling the same generating payload does not trigger parent rerender churn. Track the last consumed `retryVersion`; when it increases, call `loadAssessment({ showLoading: true })` for `reload` and `retryFailedAssessment()` for `restart`. Ignore retry signals unless the current reported state is failed.

- [ ] **Step 4: Preserve individual recovery controls**

Keep each failed child’s own Retry button. Both the local button and parent signal must enter the same retry helper, clear only that child’s failure, and prevent a second POST while its retry is active.

- [ ] **Step 5: Run child regressions**

```bash
rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/inline-practice-assessment.test.tsx
rtk npm --prefix frontend run typecheck
```

Expected: PASS, including polling, stale response, structured readiness, answering, and Markdown safety tests.

- [ ] **Step 6: Commit the child contract**

```bash
rtk git add frontend/components/chapter/practiceAssessmentState.ts frontend/__tests__/practice-assessment-state.test.ts frontend/components/chapter/InlinePracticeAssessment.tsx frontend/__tests__/inline-practice-assessment.test.tsx
rtk git commit -m "feat(practice): report per-section extraction state"
```

### Task 3: Aggregate Mixed Practice States in the Chapter Test

**Files:**
- Modify: `frontend/components/chapter/practiceAssessmentState.ts`
- Modify: `frontend/components/chapter/ChapterTestClient.tsx`
- Modify: `frontend/__tests__/practice-assessment-state.test.ts`
- Modify: `frontend/__tests__/chapter-test-client.test.tsx`

**Interfaces:**
- Produces `summarizePracticeSections(states, total)` returning ready, generating, loading, failed, and question counts.
- `ChapterTestClient` keeps `Record<sectionId, PracticeSectionState>` and `Record<sectionId, number>` retry versions.
- Adds aggregate copy, “Retry failed (N),” and “Continue with ready (N)” controls.

- [ ] **Step 1: Write failing aggregate helper tests**

```ts
it("summarizes mixed practice states without treating missing callbacks as ready", () => {
  const summary = summarizePracticeSections(
    {
      "sec-ready": readyState("sec-ready", 4),
      "sec-running": generatingState("sec-running"),
      "sec-failed": failedState("sec-failed", "restart"),
    },
    4,
  );
  expect(summary).toEqual({
    ready: 1,
    generating: 1,
    loading: 1,
    failed: 1,
    questions: 4,
    total: 4,
  });
});
```

Add zero-section and all-ready cases.

- [ ] **Step 2: Write failing chapter interaction tests**

Mock `InlinePracticeAssessment` so tests can emit state changes and inspect retry versions. Assert:

```tsx
expect(screen.getByRole("status", { name: "Practice readiness" })).toHaveTextContent(
  "1 of 3 ready · 1 preparing · 1 needs retry",
);
await user.click(screen.getByRole("button", { name: "Retry failed (1)" }));
expect(retryVersionFor("sec-failed")).toBe(1);
expect(retryVersionFor("sec-ready")).toBe(0);
expect(retryVersionFor("sec-running")).toBe(0);
```

Assert the retry button disables until the failed child leaves `failed`, the ready child’s questions remain mounted, the textbook-source disclosures remain operable, and the chapter-test generation button remains available.

- [ ] **Step 3: Run chapter tests and confirm failure**

```bash
rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/chapter-test-client.test.tsx
```

Expected: FAIL because the parent does not collect child status.

- [ ] **Step 4: Implement derived aggregation and selective retry**

Seed missing children as `loading` by passing the known `practiceSections.length` into the pure summary helper; do not create a state-reset effect. Ignore callback states whose section ID is not in the current chapter. On chapter changes, tag the state map with `courseId:chapterLabel` and derive an empty map when the tag is stale, matching existing response-staleness patterns in the frontend.

“Retry failed (N)” increments retry versions for the failed IDs captured at click time and sets an aggregate `retrying` guard. Clear that guard once none of those IDs remains failed. Do not call `startPracticeAssessment()` from the parent.

- [ ] **Step 5: Add degraded-mode navigation**

When at least one section is ready and another is loading, generating, or failed, show “Continue with ready (N).” Clicking it focuses and scrolls to the first ready assessment’s section container. Use a real button, stable section anchors, `scrollIntoView({ block: "start" })`, and focus a `tabIndex={-1}` heading so keyboard and screen-reader users receive the same context.

- [ ] **Step 6: Run chapter and type checks**

```bash
rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/inline-practice-assessment.test.tsx __tests__/chapter-test-client.test.tsx
rtk npm --prefix frontend run typecheck
rtk npm --prefix frontend run lint
```

Expected: PASS with no duplicate POSTs and no loss of ready content.

- [ ] **Step 7: Commit aggregate recovery**

```bash
rtk git add frontend/components/chapter/practiceAssessmentState.ts frontend/components/chapter/ChapterTestClient.tsx frontend/__tests__/practice-assessment-state.test.ts frontend/__tests__/chapter-test-client.test.tsx
rtk git commit -m "feat(chapter-test): recover failed practice sections"
```

### Task 4: Render Structured Recovery Guidance Per Section

**Files:**
- Modify: `openapi.json`
- Modify: `frontend/lib/api/schema.d.ts`
- Modify: `frontend/lib/api/client.ts`
- Modify: `frontend/components/chapter/InlinePracticeAssessment.tsx`
- Modify: `frontend/components/chapter/ChapterTestClient.tsx`
- Modify: `frontend/__tests__/inline-practice-assessment.test.tsx`
- Modify: `frontend/__tests__/chapter-test-client.test.tsx`

**Interfaces:**
- Consumes `PracticeAssessmentOut.error_detail` from Task 1.
- Routes `llm_readiness_unavailable` to Settings through existing `RecoveryBanner` behavior.
- Renders `invalid_model_output` as retryable invalid-format guidance.
- Aggregate UI groups failure categories without replacing each section’s detail.

- [ ] **Step 1: Regenerate the API contract**

```bash
rtk uv run python -m app.export_openapi ../openapi.json
rtk npm --prefix frontend run gen:api
```

Run the OpenAPI command with `backend` as the working directory and the npm command from the repository root.

- [ ] **Step 2: Write failing structured-guidance tests**

```tsx
it("shows invalid model output as a retryable section failure", async () => {
  mockedGetPracticeAssessment.mockResolvedValue(
    ok(
      makeAssessment({
        status: "failed",
        questions: [],
        message: "The model returned an invalid question format.",
        error_detail: {
          code: "invalid_model_output",
          failure_category: "structured_output_invalid",
          message: "The model returned an invalid question format.",
        },
      }),
    ),
  );
  renderPracticeChild({ retryVersion: 0 });
  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid question format/i);
  expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
});
```

Add chapter-level assertions for “2 sections need a valid model response” and for mixed readiness plus invalid output. Assert raw JSON/parser text is absent.

- [ ] **Step 3: Route detail through existing recovery components**

Pass `assessment.error_detail` to `RecoveryBanner`. Preserve the child’s explicit retry callback for `invalid_model_output`; preserve Settings routing for unavailable Ollama models. At aggregate level, derive category counts from child state and show concise learner copy only. Do not concatenate raw messages from multiple sections.

- [ ] **Step 4: Run structured UI tests**

```bash
rtk npm --prefix frontend test -- --run __tests__/inline-practice-assessment.test.tsx __tests__/chapter-test-client.test.tsx
rtk npm --prefix frontend run typecheck
```

Expected: PASS with safe, actionable failure copy.

- [ ] **Step 5: Commit structured recovery UI**

```bash
rtk git add openapi.json frontend/lib/api/schema.d.ts frontend/lib/api/client.ts frontend/components/chapter/InlinePracticeAssessment.tsx frontend/components/chapter/ChapterTestClient.tsx frontend/__tests__/inline-practice-assessment.test.tsx frontend/__tests__/chapter-test-client.test.tsx
rtk git commit -m "fix(chapter-test): explain practice extraction failures"
```

### Task 5: Prove Mixed-State Chapter Practice End to End

**Files:**
- Create: `frontend/e2e/chapter-test-practice-recovery.spec.ts`
- Modify: `ultraqa-comprehensive-feature-audit/report.md`

**Interfaces:**
- Consumes Tasks 1–4 and streamed generation plan Tasks 1–5.
- Produces browser evidence for partial readiness, selective retry, model unavailability, and invalid structured output.

- [ ] **Step 1: Add deterministic browser scenarios**

```ts
test("ready practice remains usable while sibling sections are generating", runPartialReadiness);
test("retry failed restarts only failed practice sections", runSelectiveRetry);
test("invalid model output offers retry without exposing parser details", runInvalidOutputRecovery);
test("missing Ollama model routes the student to Settings", runMissingModelRecovery);
test("chapter test generation remains available during partial practice failure", runIndependentTestGeneration);
```

Use route interception or seeded local jobs so tests never call a paid provider. Assert the number and section IDs of POST requests. Run `@axe-core/playwright` in mixed and failed states.

- [ ] **Step 2: Run backend practice tests three times**

```bash
rtk uv run pytest -q backend/tests/test_practice_service.py backend/tests/test_practice_api.py backend/tests/test_practice_extraction.py
rtk uv run pytest -q backend/tests/test_practice_service.py backend/tests/test_practice_api.py backend/tests/test_practice_extraction.py
rtk uv run pytest -q backend/tests/test_practice_service.py backend/tests/test_practice_api.py backend/tests/test_practice_extraction.py
```

Expected: all three runs pass without duplicate jobs or parse-repair flakiness.

- [ ] **Step 3: Run frontend and browser verification**

```bash
rtk npm --prefix frontend run typecheck
rtk npm --prefix frontend run lint
rtk npm --prefix frontend test -- --run
rtk npm --prefix frontend run test:e2e -- chapter-test-practice-recovery.spec.ts
```

Expected: PASS with no critical accessibility violations.

- [ ] **Step 4: Run the repository release gate**

```bash
rtk ./build.sh
```

Expected: `BUILD OK`.

- [ ] **Step 5: Record evidence and commit the completed slice**

Update the QA report with exact test counts, selective-retry request evidence, invalid-output recovery, model-unavailable routing, and the degraded-mode behavior.

```bash
rtk git add frontend/e2e/chapter-test-practice-recovery.spec.ts ultraqa-comprehensive-feature-audit/report.md
rtk git commit -m "test(e2e): verify chapter practice recovery"
```
