# Comprehensive User QA Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every evidence-backed issue from the comprehensive user audit, add regression coverage for the affected user journeys, and finish with a clean security, build, browser, and full-suite release gate.

**Architecture:** Preserve inline PDF viewing while treating uploaded HTML, Markdown, and text originals as downloads. Carry one structured LLM failure contract through immediate requests and queued jobs, validate selected Ollama completion and embedding capabilities with a bounded freshness policy, and make Ollama failures recover through Settings without silently falling back to a paid provider. Harden the release boundary with supported Next.js upgrades, generated-contract drift detection, minimal safe headers, Playwright/axe browser tests, and full verification.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, httpx, pytest, Next.js 16, React 19, TypeScript, Vitest, Testing Library, Playwright, axe-core.

## Global Constraints

- Work only in `/private/tmp/sourcemind-student-experience/smv2` on `codex/student-experience-remediation`.
- Follow strict red-green-refactor: every behavior change starts with a test that fails for the expected reason.
- Keep PDF delivery inline. Serve original HTML, Markdown, and plain text as attachments.
- Add `X-Content-Type-Options: nosniff`; do not add HSTS to the loopback HTTP development topology.
- Do not add a global CSP in this plan; the root layout has an inline bootstrap script and requires a separate nonce/hash design.
- Ollama remains explicit and cost-first when selected. Never silently fall back from Ollama to Anthropic or spend API credits.
- Model lists contain only currently installed completion-capable Ollama models, using exact identifiers returned by Ollama.
- A missing configured Ollama completion model is a readiness failure that blocks job creation and routes the user to Settings.
- A missing embedding model disables only the embedding capability; completion may remain available and lexical fallback remains valid.
- Ollama readiness cache TTL is 30 seconds. Generation forces a live check when no matching successful check exists or the cached check is older than 30 seconds.
- Upgrade `next` and `eslint-config-next` together from `16.2.10` to `16.3.0`; do not use package overrides.
- Add only `@playwright/test` and `@axe-core/playwright` for browser coverage. Coverage thresholds remain deferred until a measured baseline exists.
- Preserve all user-owned changes in the primary checkout.

---

### Task 1: Secure Original Source Delivery Without Breaking PDF Reading

**Files:**
- Modify: `backend/app/routers/assets.py:115-137`
- Test: `backend/tests/test_asset_upload.py`
- Test: `backend/tests/test_simple_import_adapters.py`

**Interfaces:**
- Consumes: `resolve_asset_file_path(asset_id) -> (path, filename, media_type, source_format)`.
- Produces: source-aware `FileResponse` headers: inline PDF, attachment non-PDF, and `nosniff` for every original source.

- [ ] **Step 1: Write failing source-delivery regression tests**

Add tests that upload or seed PDF, HTML, Markdown, and text assets and make these literal assertions:

```python
response = client.get(f"/api/assets/{asset_id}/file")
assert response.status_code == 200
assert response.headers["x-content-type-options"] == "nosniff"
assert "inline" in response.headers["content-disposition"]       # PDF only
assert "attachment" in response.headers["content-disposition"]   # HTML/MD/TXT only
```

The hostile HTML case must use `backend/tests/fixtures/imports/html/malicious.html`, assert the body bytes are preserved, and assert the filename cannot inject response-header characters.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
rtk uv run pytest -q backend/tests/test_asset_upload.py backend/tests/test_simple_import_adapters.py
```

Expected: the new non-PDF cases fail because the route currently returns `Content-Disposition: inline`; the header case fails because `X-Content-Type-Options` is absent.

- [ ] **Step 3: Implement the minimal source-aware response policy**

In `get_asset_file`, derive the disposition from the detected source metadata:

```python
is_pdf = source_format == "pdf" or media_type == "application/pdf"
return FileResponse(
    path,
    media_type=media_type,
    filename=_sanitize_download_filename(...),
    content_disposition_type="inline" if is_pdf else "attachment",
    headers={"X-Content-Type-Options": "nosniff"},
)
```

Do not sanitize or rewrite the stored body; the boundary is response disposition and sniffing protection.

- [ ] **Step 4: Verify GREEN and run the HTML conversion security tests**

Run:

```bash
rtk uv run pytest -q backend/tests/test_asset_upload.py backend/tests/test_simple_import_adapters.py backend/tests/test_html_conversion.py
```

Expected: all pass; converted HTML page CSP/SAMEORIGIN behavior remains unchanged.

- [ ] **Step 5: Commit the task**

```bash
rtk git add backend/app/routers/assets.py backend/tests/test_asset_upload.py backend/tests/test_simple_import_adapters.py
rtk git commit -m "fix(assets): prevent inline execution of source files"
```

---

### Task 2: Make Ollama Readiness Model-Aware and Fresh

**Files:**
- Modify: `backend/app/llm/probe.py`
- Modify: `backend/app/services/llm_readiness_service.py`
- Modify: `backend/app/schemas.py` only if the public capability/error contract requires generated-schema changes
- Test: `backend/tests/test_llm_status.py`
- Test: `backend/tests/test_llm_provider.py`
- Test: `backend/tests/test_settings_api.py`

**Interfaces:**
- Consumes: `config.llm_model()`, `config.embed_model()`, `config.ollama_base_url()`.
- Produces: a model-aware probe result with completion and embedding capability booleans, a safe failure category/remediation, and a 30-second monotonic freshness check.
- Produces: `assert_ready_for_generation()` that performs a live check only when the matching cache entry is missing or stale.

- [ ] **Step 1: Write failing readiness contract tests**

Add tests for these independent outcomes:

```python
assert payload["available"] is False
assert payload["capabilities"]["completion"] is False
assert payload["failure_category"] == "ollama_model_unavailable"
```

for a missing configured completion model, and:

```python
assert payload["available"] is True
assert payload["capabilities"] == {"completion": True, "embeddings": False}
assert payload["failure_category"] == "ollama_embed_model_unavailable"
```

for a valid completion model with a missing embedding model. Add a generation preflight test proving a stale/missing check produces structured HTTP 503 before a job row is created, while a fresh successful matching check is reused within 30 seconds.

- [ ] **Step 2: Verify RED**

Run:

```bash
rtk uv run pytest -q backend/tests/test_llm_status.py backend/tests/test_llm_provider.py backend/tests/test_settings_api.py
```

Expected: model-removal and embedding-capability tests fail because current readiness checks only `/api/version` and assumes embeddings.

- [ ] **Step 3: Extend the bounded Ollama probe**

Use loopback-only configured URLs already validated by the Settings security boundary. Probe `/api/show` with exact configured names, redirects disabled, five-second total/request bounds, and response-size validation. The public result must distinguish:

```python
ProbeResult(
    available=True,
    completion=True,
    embeddings=False,
    failure_category="ollama_embed_model_unavailable",
    failure="Install the configured Ollama embedding model to enable semantic retrieval.",
)
```

Do not enumerate all models during generation; validate only the configured completion and embedding identifiers.

- [ ] **Step 4: Add 30-second cache freshness to readiness**

Store the monotonic check time only in the private cache record. A cache entry is reusable only when identity matches and:

```python
time.monotonic() - checked_monotonic < 30.0
```

`assert_ready_for_generation()` calls `check_payload()` when the matching cache is absent/stale, then requires `capabilities.completion`. Keep the public `last_checked_at` ISO timestamp and never expose the monotonic value.

- [ ] **Step 5: Verify GREEN and preflight behavior**

Run the focused command from Step 2 plus generation API tests that cover cards, lessons, tests, chat, practice, jobs, and curriculum readiness.

Expected: missing completion models block before job creation; missing embedding models preserve completion and lexical fallback; no Anthropic request occurs for selected Ollama.

- [ ] **Step 6: Regenerate OpenAPI artifacts when schemas changed**

Run:

```bash
rtk uv run python scripts/export_openapi.py
rtk npm --prefix frontend run api:generate
```

- [ ] **Step 7: Commit the task**

```bash
rtk git add backend/app/llm/probe.py backend/app/services/llm_readiness_service.py backend/app/schemas.py backend/tests/test_llm_status.py backend/tests/test_llm_provider.py backend/tests/test_settings_api.py openapi.json frontend/lib/api/schema.d.ts
rtk git commit -m "fix(llm): validate configured Ollama capabilities"
```

---

### Task 3: Unify Structured LLM Recovery Across Every Student Entry Point

**Files:**
- Modify: `frontend/components/RecoveryBanner.tsx`
- Modify: `frontend/components/tests/GenerateTestCard.tsx`
- Modify: `frontend/components/chapter/ChapterTestClient.tsx`
- Modify: `frontend/components/reader/GenerateAllLessons.tsx`
- Modify: `frontend/components/reader/LessonPane.tsx`
- Modify: `frontend/components/reader/QuizzesPanel.tsx`
- Modify: `frontend/components/flashcards/ChapterDeckCard.tsx`
- Modify: `frontend/components/reader/CourseChatDrawer.tsx`
- Modify: `frontend/components/Chat.tsx`
- Modify: `frontend/components/chapter/InlinePracticeAssessment.tsx`
- Modify: `frontend/lib/hooks/useJobFailureMessage.ts` only to remove consumers after migration; reuse `useJobFailure` for structured failures
- Test: `frontend/__tests__/recovery-banner.test.tsx`
- Test: `frontend/__tests__/tests-page.test.tsx`
- Test: `frontend/__tests__/chapter-test-client.test.tsx`
- Test: `frontend/__tests__/generate-all-lessons.test.tsx`
- Test: `frontend/__tests__/lesson-pane.test.tsx`
- Test: `frontend/__tests__/quizzes-panel.test.tsx`
- Test: `frontend/__tests__/chapter-deck-card.test.tsx`
- Test: `frontend/__tests__/chat.test.tsx`
- Test: `frontend/__tests__/annotations/explain-in-chat.test.tsx`
- Test: `frontend/__tests__/inline-practice-assessment.test.tsx`

**Interfaces:**
- Consumes: `describeError(status, action, error) -> FetchError` and `useJobFailure(jobId) -> FetchError | null`.
- Produces: every LLM action retains `FetchError.detail`, renders `RecoveryBanner`, routes readiness categories to `/settings`, and suppresses retry for readiness failures.

- [ ] **Step 1: Write direct RecoveryBanner category tests**

Use literal details for `llm_readiness_unavailable`, `missing_credentials`, `unknown_provider`, `unreachable`, `ollama_model_unavailable`, and `ollama_embed_model_unavailable`. Assert Settings routing/no retry for readiness failures, and Jobs routing/retry for ordinary worker failures.

- [ ] **Step 2: Write one failing immediate-503 test for every affected entry point**

Each API mock returns the complete real error shape:

```ts
{
  ok: false,
  status: 503,
  error: {
    detail: {
      code: "llm_readiness_unavailable",
      failure_category: "ollama_model_unavailable",
      message: "Your configured Ollama model is not present.",
      remediation: "Open Settings and select a currently installed model.",
    },
  },
}
```

Assert the message, `Open Settings` link, absence of retry, and absence of EventSource/job polling when the start request never created a job.

- [ ] **Step 3: Write failing watched-job tests where detail is currently lost**

For `ChapterTestClient` and `ChapterDeckCard`, make `getJob` return a failed job with the same structured `error_detail`. Assert Settings routing and preserved job-details linkage where applicable.

- [ ] **Step 4: Verify RED**

Run all test files listed above. Expected: current generic/plain banners fail the Settings-link and retry-suppression assertions.

- [ ] **Step 5: Implement the shared state/rendering contract**

For immediate actions, destructure all result fields and retain the object:

```ts
const { data, status, error } = await generateTest(...);
if (!data) setActionError(describeError(status, "Starting test generation", error));
```

Use `FetchError | null` state and render:

```tsx
<RecoveryBanner
  message={actionError.message}
  errorDetail={actionError.detail}
  jobId={jobId}
  onRetry={retry}
/>
```

For watched jobs, use `useJobFailure()` rather than message-only adapters. Extend the readiness-category predicate for both Ollama model categories. Do not duplicate category logic in feature components.

- [ ] **Step 6: Preserve chat/practice state semantics**

Chat must not duplicate a pending student message after a readiness failure. Inline practice retry failure must keep the prior failed assessment state visible rather than pretending generation restarted.

- [ ] **Step 7: Verify GREEN and the complete critical frontend slice**

Run the focused files, then repeat the nine-file critical frontend slice three times. Expected: zero failures, zero unhandled promise warnings, and consistent Settings recovery everywhere.

- [ ] **Step 8: Commit the task**

Stage only the production/test files in this task and commit:

```bash
rtk git commit -m "fix(ui): standardize AI readiness recovery"
```

---

### Task 4: Upgrade Next.js and Enforce Release Integrity Headers/Gates

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/next.config.ts`
- Modify: `backend/app/main.py`
- Modify: `build.sh`
- Test: `backend/tests/test_health.py` or create `backend/tests/test_security_headers.py`

**Interfaces:**
- Produces: Next.js `16.3.0`, matching ESLint config, supported transitive PostCSS/Sharp versions, minimal frontend/backend headers, and a build that fails when generated artifacts drift.

- [ ] **Step 1: Write failing backend header tests**

Assert `/health` includes:

```python
assert response.headers["x-content-type-options"] == "nosniff"
assert response.headers["x-frame-options"] == "SAMEORIGIN"
assert response.headers["referrer-policy"] == "no-referrer"
assert "strict-transport-security" not in response.headers
```

- [ ] **Step 2: Verify RED and add minimal backend middleware**

Run the header test, confirm the missing-header failure, then add middleware that uses `setdefault` so endpoint-specific policies remain authoritative.

- [ ] **Step 3: Upgrade the supported Next packages**

Run in `frontend`:

```bash
rtk npm install --save-exact next@16.3.0
rtk npm install --save-dev --save-exact eslint-config-next@16.3.0
```

Assert the lock contains Next `16.3.0`, nested PostCSS `8.5.23`, and Sharp `0.35.3` or later.

- [ ] **Step 4: Add frontend header configuration**

Set `poweredByHeader: false` and a `headers()` rule for `/:path*` with `nosniff`, `SAMEORIGIN`, and `no-referrer`. Do not add CSP or HSTS.

- [ ] **Step 5: Add the generated-contract drift gate**

Immediately after OpenAPI/client generation in `build.sh`, run:

```bash
git diff --exit-code -- openapi.json frontend/lib/api/schema.d.ts
```

Verify behavior, not source text: in a disposable copy of one generated file, alter one byte, run the gate and assert non-zero, then restore the file and assert zero.

- [ ] **Step 6: Run security/build checks**

Run lint, typecheck, frontend unit tests, Next build, backend header tests, `npm audit --omit=dev --audit-level=high`, and explicit generated-artifact diff.

- [ ] **Step 7: Commit the task**

```bash
rtk git add frontend/package.json frontend/package-lock.json frontend/next.config.ts backend/app/main.py backend/tests/test_security_headers.py build.sh
rtk git commit -m "chore(security): harden release dependencies and gates"
```

---

### Task 5: Add Real Browser, Mobile, and Accessibility Regression Coverage

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/app-navigation.spec.ts`
- Create: `frontend/e2e/pdf-default.spec.ts`
- Create: `frontend/e2e/llm-recovery.spec.ts`
- Create: `frontend/e2e/settings-ollama.spec.ts`
- Create: `frontend/e2e/accessibility.spec.ts`
- Create: `frontend/e2e/support/test-data.ts`

**Interfaces:**
- Consumes: local backend on `127.0.0.1:8000`, frontend on `127.0.0.1:3000`, existing fixtures/APIs, and Playwright request routing for deterministic readiness failures.
- Produces: browser tests for every route shell, clickability, PDF default, Ollama dropdown behavior, recovery navigation, mobile controls, and critical axe violations.

- [ ] **Step 1: Install only the approved browser dependencies**

```bash
rtk npm install --save-dev --save-exact @playwright/test @axe-core/playwright
rtk npx playwright install chromium
```

Add `test:e2e` and `test:e2e:headed` scripts without changing the unit-test script.

- [ ] **Step 2: Add a deterministic local Playwright configuration**

Use Chromium, one worker, traces on first retry, screenshots only on failure, base URL `http://127.0.0.1:3000`, and two `webServer` entries for backend/frontend with `reuseExistingServer: true` outside CI.

- [ ] **Step 3: Write navigation/clickability and mobile tests**

Exercise `/`, `/flashcards`, `/jobs`, `/review`, `/search`, `/settings`, and `/tests`; assert each page has one visible heading/main landmark, no uncaught page errors, and at least the primary navigation/control can be clicked. At a 390×844 viewport, open/close the sidebar and chat/settings controls without an overlay blocking clicks.

- [ ] **Step 4: Write PDF-default test with disposable data**

Create a course and upload a real PDF fixture through API setup. Navigate to the course and assert Pages/PDF is the selected reader mode on first open. Delete the disposable course in `afterEach`, even after assertion failure.

- [ ] **Step 5: Write deterministic LLM recovery and Ollama dropdown tests**

Intercept only the relevant start request to return structured 503. Assert the control remains clickable, the banner shows the backend message, and `Open Settings` navigates correctly. For Settings, exercise provider selection and dropdown focus/click; assert only the mocked current completion models appear and a configured missing model produces the approved warning.

- [ ] **Step 6: Add axe checks**

For the seven static route shells and a representative course reader, assert zero critical axe violations. Keep serious/moderate findings visible in the report but do not create an arbitrary global threshold in this task.

- [ ] **Step 7: Run browser tests in desktop and mobile projects**

```bash
rtk npm run test:e2e
```

Expected: all tests pass with cleanup; no disposable course remains; no external LLM request occurs.

- [ ] **Step 8: Commit the task**

```bash
rtk git add frontend/package.json frontend/package-lock.json frontend/playwright.config.ts frontend/e2e
rtk git commit -m "test(e2e): cover student journeys and accessibility"
```

---

### Task 6: Close the Comprehensive QA Audit and Release Gate

**Files:**
- Modify: `ultraqa-comprehensive-feature-audit/report.md`
- Modify: only files required to fix evidence-backed failures found by this final gate

**Interfaces:**
- Consumes: Tasks 1-5 and the original scenario matrix.
- Produces: a requirement-by-requirement completion audit with fresh command evidence, cleanup proof, independent review, and a pushed branch.

- [ ] **Step 1: Run targeted suites three times**

Repeat the security/import/settings/readiness backend slice and the critical frontend LLM/reader/settings slice three times. Record exact counts and any flake.

- [ ] **Step 2: Run the full release gate**

Stop dev servers temporarily, then run:

```bash
rtk env UV_CACHE_DIR=/private/tmp/uv-cache ./build.sh
rtk npm --prefix frontend run lint
rtk npm --prefix frontend audit --omit=dev --audit-level=high
rtk uvx pip-audit --path backend/.venv/lib/python3.12/site-packages
rtk npm --prefix frontend run test:e2e
rtk git diff --exit-code -- openapi.json frontend/lib/api/schema.d.ts
```

Restore the local dev servers afterward.

- [ ] **Step 3: Re-run the live adversarial matrix**

Verify inline PDF, non-inline hostile HTML, CSRF/origin rejection, Ollama SSRF rejection, current-model discovery, missing-model readiness, malformed search, disposable import/progress/search/highlight/export/delete lifecycle, global headers, and all route shapes.

- [ ] **Step 4: Update every scenario row and evidence field**

No `FAIL`, unresolved `PARTIAL`, or `Pending` row may remain without a genuine environment blocker. Record exact commands, counts, browser version, dependency versions, cleanup IDs, and residual risks.

- [ ] **Step 5: Run independent whole-branch code review and one fix wave**

Review security, correctness, regressions, test quality, data cleanup, dependency compatibility, and user experience. Resolve every Critical/Important finding and re-run its covering tests.

- [ ] **Step 6: Commit, push, and verify remote synchronization**

```bash
rtk git add ultraqa-comprehensive-feature-audit/report.md
rtk git commit -m "docs(qa): record comprehensive user verification"
rtk git push origin codex/student-experience-remediation
rtk git status --short
rtk git rev-parse HEAD
rtk git rev-parse origin/codex/student-experience-remediation
```

Expected: clean tracked worktree, matching local/remote commit IDs, dev servers healthy, and all temporary data removed.
