# Student AI Readiness and Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit provider-readiness, safe local settings, and a jobs surface so AI failures become actionable instead of dead ends.

**Architecture:** Use one readiness service as the source of truth for AI availability, keep credentials file-backed in `data/secrets.toml`, and keep the frontend recovery path simple: one Settings surface for provider setup and one Jobs surface for active/recent job inspection. The backend blocks generation before enqueue when capability is unavailable, the frontend turns each failure into either a Settings fix or a Jobs drill-down instead of a generic retry loop, and the per-process CSRF token is bootstrapped through a no-store response and sent only as an in-memory request header.

**Tech Stack:** FastAPI, SQLAlchemy 2, SQLite, Pydantic/OpenAPI, Next.js App Router, React 19, TypeScript, Vitest, pytest. No new runtime dependency is required for this slice.

## Scope

This plan covers:

- provider readiness/status reporting;
- local-only provider/model/credential settings;
- generation preflight gating before jobs are created;
- a grouped Jobs surface with retry where the job contract permits it;
- frontend recovery links that send students to Settings or Jobs based on the failure class;
- OpenAPI export and generated TypeScript client refresh.

This plan does not cover review semantics, sample-course identity, workspace modes, search, responsive shell work, or import-format expansion.

## Global Constraints

- Preserve SourceMind's local-first, single-user architecture and the existing deterministic-before-generative rule.
- No remote authentication, cloud storage, or cross-device sync.
- The backend accepts credentials only from a loopback client and a same-origin JSON request carrying a per-process CSRF token.
- Secrets are written atomically to `data/secrets.toml` with owner-only permissions.
- A failed settings write must not leave a partial file behind, and the on-disk file mode must remain owner-only after successful writes.
- Existing secrets are never returned to the browser; the UI receives only `configured: true|false`.
- Secrets never enter logs, job payloads, error details, API schemas, test snapshots, or LLM usage records.
- The CSRF bootstrap response and every settings mutation response use `Cache-Control: no-store`.
- The per-process CSRF token is kept in memory only, is never persisted as a credential, and is sent on mutation requests in a dedicated header such as `X-CSRF-Token`.
- `GET /api/llm/status` reads configuration without making a network call.
- `POST /api/llm/status/check` performs an explicit provider-specific connectivity check.
- Connectivity checks are never triggered on ordinary page load, never generate learning content, and never create ledger cost entries unless the provider has no non-billable verification operation; in that case the result remains `configured_unverified` and the UI says so.
- A fresh installation with no provider configured can upload, read, search, annotate, export, and review existing cards without seeing a raw environment-variable error.
- Failed historical jobs remain inspectable and do not block current course use.
- Retry is disabled while the underlying capability remains unavailable.
- No test may call an external provider or network service. Provider checks, status variants, and parser behavior use deterministic fixtures and stubs.
- The rollout flag is `SMV2_AI_READINESS_UI` on the backend and `NEXT_PUBLIC_SMV2_AI_READINESS_UI` on the frontend; it gates credential-editing controls only, not the discoverability of the Jobs/Settings navigation. The flag starts off by default, then the plan must explicitly verify the enabled-by-default path with targeted tests, a full build, and manual local e2e before the flag is removed or documented as intentionally retained.

## File Structure

- `backend/app/services/llm_readiness_service.py` owns the canonical provider-readiness contract, capability labels, sanitized failure categories, and explicit connection-check behavior.
- `backend/app/services/local_settings_service.py` owns reading and writing `data/secrets.toml`, redacting stored credentials, and mapping provider/model choices to the persisted local settings shape.
- `backend/app/security/local_settings.py` owns the loopback-only and same-origin CSRF guard used by any credential-writing endpoint.
- `backend/app/security/local_settings.py` also owns the no-store CSRF bootstrap response and the helper that validates the per-process token from the request header.
- `backend/app/routers/llm_usage.py` keeps the existing usage route and adds the readiness/status routes under the existing `/api/llm` prefix.
- `backend/app/routers/settings.py` owns the Settings CRUD, the CSRF bootstrap route, and the connection-test routes.
- `backend/app/services/jobs_service.py` owns retry dispatch and any job lookup helpers needed by the retry endpoint.
- `backend/app/jobs/registry.py` owns the retryable-job allowlist so the UI never offers a retry button for a non-idempotent job type.
- `backend/app/routers/jobs.py` keeps the raw list/detail routes and adds the explicit retry route.
- `backend/app/schemas.py` owns the new readiness, settings, and retry response/request models.
- `backend/app/main.py` wires the new routers into the app.
- `frontend/app/settings/page.tsx` and `frontend/components/settings/*` own the provider/model/credential UI.
- `frontend/app/jobs/page.tsx` and `frontend/components/jobs/*` own the grouped jobs feed and retry affordances.
- `frontend/components/RecoveryBanner.tsx` owns the shared failure CTA that points to Settings or Jobs.
- `frontend/components/AppSidebar.tsx` owns top-level navigation links for the new surfaces and keeps them visible even when the credential-editing flag is off.
- `frontend/lib/security/csrf.ts` owns the in-memory CSRF token bootstrap state and header injection for credential mutations.
- `frontend/lib/api/client.ts` owns the typed API helpers for the new backend routes.
- `backend/tests/*` and `frontend/__tests__/*` own the failing-first regression coverage.

There is no Alembic migration in this slice because credentials stay file-backed in `data/secrets.toml`; if a database table appears in the plan, the scope has drifted.

## Task 1: Backend readiness, settings, and preflight gates

**Files:**
- Create: `backend/app/services/llm_readiness_service.py`
- Create: `backend/app/services/local_settings_service.py`
- Create: `backend/app/security/local_settings.py`
- Create: `backend/app/routers/settings.py`
- Modify: `backend/app/routers/llm_usage.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/lessons_service.py`
- Modify: `backend/app/services/cards_service.py`
- Modify: `backend/app/services/tests_service.py`
- Modify: `backend/app/services/practice_service.py`
- Modify: `backend/app/services/curriculum_service.py`
- Modify: `backend/app/services/adaptive_study_service.py`
- Modify: `backend/app/pipeline/concept_extraction.py`
- Modify: `backend/app/pipeline/concept_practice_generation.py`
- Modify: `backend/app/pipeline/practice_extraction.py`
- Modify: `backend/app/pipeline/quiz_generation.py`
- Modify: `backend/tests/test_lesson_generation.py`
- Modify: `backend/tests/test_cards_generation.py`
- Modify: `backend/tests/test_practice_extraction.py`
- Modify: `backend/tests/test_quiz.py`
- Modify: `backend/tests/test_chat.py`
- Create: `backend/tests/test_llm_status.py`
- Create: `backend/tests/test_settings_api.py`
- Create: `backend/tests/test_settings_security.py`
- Create: `backend/tests/test_local_settings_service.py`

**Interfaces:**
- `GET /api/llm/status` returns provider, model, config state, supported capabilities, last check time, sanitized failure category, and remediation text. It never makes a network call.
- `POST /api/llm/status/check` performs the explicit provider-specific connectivity check and returns the same shape after the check.
- `GET /api/settings` returns the current provider/model selection, credential presence booleans, rollout state, and a redacted readiness summary.
- `GET /api/settings/bootstrap` returns the per-process CSRF token and rollout metadata with `Cache-Control: no-store`; the frontend reads this once per session and keeps the token in memory only.
- `PUT /api/settings` updates provider/model and writes local credentials only when the request passes the loopback and CSRF guards.
- `DELETE /api/settings` or a provider-scoped clear route removes only the selected provider's local credential after an explicit confirmation.
- The generation entry points short-circuit before job creation when readiness is unavailable, and they return a stable 503/409 style error with a recovery hint instead of surfacing a raw provider message.

- [ ] **Step 1: Write the failing tests first.**
  - Add `backend/tests/test_llm_status.py` for the status payload, status-check behavior, and redaction rules.
  - Add `backend/tests/test_settings_api.py` for provider/model persistence, credential writes, credential clears, and the happy-path check flow.
  - Add `backend/tests/test_settings_security.py` for loopback rejection, missing-CSRF rejection, mismatched-origin rejection, no-store headers, and secret redaction in both responses and logs.
  - Add `backend/tests/test_local_settings_service.py` for atomic secret writes, owner-only mode, and the no-partial-file-on-failure guarantee.
  - Update the generation tests so unconfigured AI surfaces fail before enqueueing a job and return an actionable response instead of creating a doomed job row.

- [ ] **Step 2: Prove the tests fail with the current code.**
  - Run:
    ```sh
    cd backend
    uv run pytest tests/test_llm_status.py tests/test_settings_api.py tests/test_settings_security.py tests/test_local_settings_service.py -q -p no:cacheprovider
    ```
  - Expected: FAIL with missing-route/missing-schema assertions because the new status and settings endpoints do not exist yet.
  - Run:
    ```sh
    cd backend
    uv run pytest tests/test_lesson_generation.py tests/test_cards_generation.py tests/test_practice_extraction.py tests/test_quiz.py tests/test_chat.py -q -p no:cacheprovider
    ```
  - Expected: FAIL with the current raw provider-not-configured path, because the generation entry points still defer to job creation or expose the wrong failure shape.

- [ ] **Step 3: Implement the backend slice with the smallest possible surface area.**
  - Build the readiness service first, then have the existing `/api/llm` router call it for status and check operations.
  - Keep the local-settings service file-backed and redacted; do not add a database table.
  - Enforce loopback and same-origin CSRF in one security helper and reuse it from every credential-writing endpoint.
  - Wire the generation entry points through a shared readiness check before `create_job` or `create_job_in_session` runs.

- [ ] **Step 4: Rerun the focused backend tests until they pass.**
  - Run:
    ```sh
    cd backend
    uv run pytest tests/test_llm_status.py tests/test_settings_api.py tests/test_settings_security.py tests/test_local_settings_service.py -q -p no:cacheprovider
    ```
  - Expected: PASS.
  - Run:
    ```sh
    cd backend
    uv run pytest tests/test_lesson_generation.py tests/test_cards_generation.py tests/test_practice_extraction.py tests/test_quiz.py tests/test_chat.py -q -p no:cacheprovider
    ```
  - Expected: PASS, with the unconfigured-provider cases failing early and leaving no new job rows behind.

- [ ] **Step 5: Commit the backend slice.**
  - Use:
    ```sh
    git status --short
    git add backend/app/config.py backend/app/main.py backend/app/routers/llm_usage.py backend/app/routers/settings.py backend/app/schemas.py backend/app/security/local_settings.py backend/app/services/chat_service.py backend/app/services/lessons_service.py backend/app/services/cards_service.py backend/app/services/tests_service.py backend/app/services/practice_service.py backend/app/services/curriculum_service.py backend/app/services/adaptive_study_service.py backend/app/pipeline/concept_extraction.py backend/app/pipeline/concept_practice_generation.py backend/app/pipeline/practice_extraction.py backend/app/pipeline/quiz_generation.py backend/app/services/llm_readiness_service.py backend/app/services/local_settings_service.py backend/tests/test_llm_status.py backend/tests/test_settings_api.py backend/tests/test_settings_security.py backend/tests/test_local_settings_service.py backend/tests/test_lesson_generation.py backend/tests/test_cards_generation.py backend/tests/test_practice_extraction.py backend/tests/test_quiz.py backend/tests/test_chat.py
    git commit -m "feat(smv2): add llm readiness and local settings backend"
    ```

## Task 2: Jobs retry contract and grouped job feed

**Files:**
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/services/jobs_service.py`
- Modify: `backend/app/routers/jobs.py`
- Modify: `backend/app/schemas.py`
- Create: `backend/tests/test_jobs_api.py`
- Modify: `backend/tests/test_jobs_noop_e2e.py`

**Interfaces:**
- `POST /api/jobs/{job_id}/retry` returns a fresh queued job only when the original job type is in the retryable allowlist and the retry contract is idempotent.
- The raw `GET /api/jobs` and `GET /api/jobs/{job_id}` routes remain available so the frontend can group by course and type without losing the underlying payload.
- Retry rejects non-retryable types with a stable 409 or 422 and does not mutate the original job row.

- [ ] **Step 1: Write the retry tests before touching the router.**
  - Add `backend/tests/test_jobs_api.py` with one retryable job case, one non-retryable job case, and one payload-preservation case.
  - Update `backend/tests/test_jobs_noop_e2e.py` if needed so the existing noop path still proves the raw jobs API is unchanged.

- [ ] **Step 2: Run the jobs tests and watch them fail.**
  - Run:
    ```sh
    cd backend
    uv run pytest tests/test_jobs_api.py tests/test_jobs_noop_e2e.py -q -p no:cacheprovider
    ```
  - Expected: FAIL because the retry route and retry allowlist do not exist yet.

- [ ] **Step 3: Implement the retry path and the retryable-job allowlist.**
  - Put the allowlist in `backend/app/jobs/registry.py` so the UI and backend share the same retry contract.
  - Make `backend/app/services/jobs_service.py` own the actual retry duplication logic, including any status resets or payload copying.
  - Keep `backend/app/routers/jobs.py` thin: existence checks in the router, business logic in the service.

- [ ] **Step 4: Rerun the jobs tests.**
  - Run:
    ```sh
    cd backend
    uv run pytest tests/test_jobs_api.py tests/test_jobs_noop_e2e.py -q -p no:cacheprovider
    ```
  - Expected: PASS.

- [ ] **Step 5: Commit the jobs backend slice.**
  - Use:
    ```sh
    git add backend/app/jobs/registry.py backend/app/services/jobs_service.py backend/app/routers/jobs.py backend/app/schemas.py backend/tests/test_jobs_api.py backend/tests/test_jobs_noop_e2e.py
    git commit -m "feat(smv2): add retryable jobs contract"
    ```

## Task 3: Frontend Settings and Jobs surfaces plus recovery routing

**Files:**
- Create: `frontend/app/settings/page.tsx`
- Create: `frontend/app/jobs/page.tsx`
- Create: `frontend/components/settings/SettingsClient.tsx`
- Create: `frontend/components/settings/SettingsForm.tsx`
- Create: `frontend/components/jobs/JobsClient.tsx`
- Create: `frontend/components/jobs/JobGroup.tsx`
- Create: `frontend/components/RecoveryBanner.tsx`
- Create: `frontend/lib/security/csrf.ts`
- Modify: `frontend/components/AppSidebar.tsx`
- Modify: `frontend/lib/api/client.ts`
- Modify: `frontend/components/reader/CardsCTA.tsx`
- Modify: `frontend/components/reader/QuizzesPanel.tsx`
- Modify: `frontend/components/reader/LessonPane.tsx`
- Modify: `frontend/components/tests/GenerateTestCard.tsx`
- Modify: `frontend/components/reader/GenerateAllLessons.tsx`
- Modify: `frontend/components/reader/SectionCards.tsx`
- Modify: `frontend/__tests__/site-header.test.tsx`
- Create: `frontend/__tests__/app-sidebar.test.tsx`
- Create: `frontend/__tests__/settings-page.test.tsx`
- Create: `frontend/__tests__/jobs-page.test.tsx`
- Modify: `frontend/__tests__/cards-cta.test.tsx`
- Modify: `frontend/__tests__/quizzes-panel.test.tsx`
- Modify: `frontend/__tests__/lesson-pane.test.tsx`
- Modify: `frontend/__tests__/tests-page.test.tsx`
- Modify: `frontend/__tests__/generate-all-lessons.test.tsx`

**Interfaces:**
- `GET /settings` shows provider selection, model selection, readiness state, and local-only credential setup, while the credential-editing controls remain disabled until the rollout flag is enabled.
- `GET /jobs` renders active and recent jobs grouped by course and type, with course/section navigation derived from the raw job payloads.
- `RecoveryBanner` renders a safe retry action plus a contextual secondary link: provider-not-configured failures go to `/settings`, and other job failures go to `/jobs?job={jobId}`.
- `AppSidebar` exposes the new navigation entries regardless of the rollout flag so the surfaces never become accidentally hidden.
- `listJobs`, `retryJob`, `getLlmStatus`, `checkLlmStatus`, `getSettings`, `saveSettings`, and `clearProviderSecret` become typed frontend helpers in `frontend/lib/api/client.ts`.
- `frontend/lib/security/csrf.ts` stores the CSRF token in memory only, and `frontend/lib/api/client.ts` sends it on credential mutations via a dedicated header.

- [ ] **Step 1: Write the frontend tests first.**
  - Add `frontend/__tests__/settings-page.test.tsx` for provider/model display, connection testing, confirm-to-clear behavior, and redacted credential state.
  - Add `frontend/__tests__/jobs-page.test.tsx` for grouped rendering, section links, `?job=` highlighting, and retry visibility only on retryable job types.
  - Add `frontend/__tests__/app-sidebar.test.tsx` for the new Jobs/Settings links and a regression that keeps them visible even when the credential-editing flag is off.
  - Update `frontend/__tests__/cards-cta.test.tsx`, `frontend/__tests__/quizzes-panel.test.tsx`, `frontend/__tests__/lesson-pane.test.tsx`, `frontend/__tests__/tests-page.test.tsx`, and `frontend/__tests__/generate-all-lessons.test.tsx` so provider-not-configured failures route to Settings and other job failures route to Jobs.
  - Add coverage that the CSRF bootstrap response is fetched with `no-store`, the token never leaves memory, and mutation requests send `X-CSRF-Token` without serializing it into app state or logs.

- [ ] **Step 2: Run the frontend tests and confirm the current UI fails.**
  - Run:
    ```sh
    cd frontend
    npm test -- --run __tests__/settings-page.test.tsx __tests__/jobs-page.test.tsx __tests__/app-sidebar.test.tsx __tests__/cards-cta.test.tsx __tests__/quizzes-panel.test.tsx __tests__/lesson-pane.test.tsx __tests__/tests-page.test.tsx __tests__/generate-all-lessons.test.tsx
    ```
  - Expected: FAIL because the new pages, helpers, and recovery banner do not exist yet.

- [ ] **Step 3: Implement the new frontend surfaces and shared recovery component.**
  - Keep the Settings page focused on local-provider setup and explicit connection testing.
  - Keep the Jobs page read-only except for retry on retryable jobs.
  - Group raw jobs client-side by course and type; use `payload.course_id`, `payload.section_id`, and the existing course/section endpoints to build links.
  - Keep failure routing deterministic: provider-not-configured means Settings, every other generation failure means Jobs.
  - Gate only the credential-editing controls behind `NEXT_PUBLIC_SMV2_AI_READINESS_UI`; do not gate the Jobs/Settings nav links themselves, because they must remain discoverable.
  - Fetch the CSRF bootstrap payload with `no-store`, keep the token in memory only, and send it on credential mutations in `X-CSRF-Token`.

- [ ] **Step 4: Rerun the frontend tests and typecheck.**
  - Run:
    ```sh
    cd frontend
    npm test -- --run __tests__/settings-page.test.tsx __tests__/jobs-page.test.tsx __tests__/app-sidebar.test.tsx __tests__/cards-cta.test.tsx __tests__/quizzes-panel.test.tsx __tests__/lesson-pane.test.tsx __tests__/tests-page.test.tsx __tests__/generate-all-lessons.test.tsx
    ```
  - Expected: PASS.
  - Run:
    ```sh
    cd frontend
    npm run typecheck
    ```
  - Expected: PASS.
  - Verify the rollout flag in two states: first with the credential-editing path off by default, then with it forced on for the targeted suite, `./build.sh`, and a manual local e2e pass. If the runtime flag is kept after that verification, the docs must state why; otherwise remove the flag path.

- [ ] **Step 5: Commit the frontend slice.**
  - Use:
    ```sh
    git add frontend/app/settings/page.tsx frontend/app/jobs/page.tsx frontend/components/settings/SettingsClient.tsx frontend/components/settings/SettingsForm.tsx frontend/components/jobs/JobsClient.tsx frontend/components/jobs/JobGroup.tsx frontend/components/RecoveryBanner.tsx frontend/components/AppSidebar.tsx frontend/lib/api/client.ts frontend/lib/security/csrf.ts frontend/components/reader/CardsCTA.tsx frontend/components/reader/QuizzesPanel.tsx frontend/components/reader/LessonPane.tsx frontend/components/tests/GenerateTestCard.tsx frontend/components/reader/GenerateAllLessons.tsx frontend/components/reader/SectionCards.tsx frontend/__tests__/site-header.test.tsx frontend/__tests__/app-sidebar.test.tsx frontend/__tests__/settings-page.test.tsx frontend/__tests__/jobs-page.test.tsx frontend/__tests__/cards-cta.test.tsx frontend/__tests__/quizzes-panel.test.tsx frontend/__tests__/lesson-pane.test.tsx frontend/__tests__/tests-page.test.tsx frontend/__tests__/generate-all-lessons.test.tsx
    git commit -m "feat(smv2): add settings and jobs surfaces"
    ```

## Task 4: Generated artifacts, rollout, and full verification

**Files:**
- Regenerate: `openapi.json`
- Regenerate: `frontend/lib/api/schema.d.ts`
- Modify: any tests that intentionally assert the generated contract

**Interfaces:**
- The OpenAPI export includes the new readiness, settings, and retry endpoints.
- The generated TypeScript client exposes the new helpers without any hand-written backend response shapes.

- [ ] **Step 1: Regenerate the backend OpenAPI schema and frontend client types.**
  - Run:
    ```sh
    cd backend
    uv run python -m app.export_openapi ../openapi.json
    ```
  - Expected: `wrote OpenAPI schema to ../openapi.json`.
  - Run:
    ```sh
    cd frontend
    npm run gen:api
    ```
  - Expected: `frontend/lib/api/schema.d.ts` updates to include the new `/api/llm/status`, `/api/llm/status/check`, `/api/settings`, and `/api/jobs/{job_id}/retry` operations.

- [ ] **Step 2: Run the narrow verification set again with the generated artifacts in place.**
  - Run:
    ```sh
    cd backend
    uv run pytest tests/test_llm_status.py tests/test_settings_api.py tests/test_settings_security.py tests/test_local_settings_service.py tests/test_jobs_api.py tests/test_lesson_generation.py tests/test_cards_generation.py tests/test_practice_extraction.py tests/test_quiz.py tests/test_chat.py -q -p no:cacheprovider
    ```
  - Expected: PASS.
  - Run:
    ```sh
    cd frontend
    npm test -- --run __tests__/settings-page.test.tsx __tests__/jobs-page.test.tsx __tests__/app-sidebar.test.tsx __tests__/cards-cta.test.tsx __tests__/quizzes-panel.test.tsx __tests__/lesson-pane.test.tsx __tests__/tests-page.test.tsx __tests__/generate-all-lessons.test.tsx
    ```
  - Expected: PASS.

- [ ] **Step 3: Run the full repository gate.**
  - Run:
    ```sh
    cd .
    ./build.sh
    ```
  - Expected: backend pytest, OpenAPI export, frontend client generation, typecheck, frontend tests, and frontend build all pass cleanly.

- [ ] **Step 4: Run the final diff sanity checks.**
  - Run:
    ```sh
    cd .
    git diff --check
    ```
  - Expected: PASS with no whitespace or patch-format errors.

- [ ] **Step 5: Enable credential editing by default and run the manual local recovery journey.**
  - Start `./dev.sh` in a dedicated terminal session. With no provider configured, confirm AI actions create no jobs and link to Settings. Configure a local or stubbed provider through Settings, confirm the connection check creates neither learning content nor usage entries, trigger a deterministic failed job, inspect it in Jobs, and confirm retry appears only for an allowlisted type. Verify the browser never receives a stored credential and responses remain redacted.
  - Stop the dedicated dev session before running any later build or release command; `build.sh` refuses to run while ports 3000/8000 are occupied.
  - Expected: the enabled-by-default credential path completes without a rollback-triggering defect.

- [ ] **Step 6: Commit the generated artifacts and verification fixes.**
  - Use:
    ```sh
    git status --short
    git add openapi.json frontend/lib/api/schema.d.ts
    git commit -m "feat(smv2): finalize ai readiness and jobs contract"
    ```

## Review Gates

- Backend gate: Task 1 is not complete until the readiness/settings/security tests and the preflight-generation tests all pass.
- Jobs gate: Task 2 is not complete until retry is allowlisted and the retry endpoint passes the jobs API tests.
- Frontend gate: Task 3 is not complete until the Settings page, Jobs page, nav links, CSRF bootstrap handling, and recovery routing tests pass.
- Release gate: Task 4 is not complete until `./build.sh` and `git diff --check` both pass with no generated-artifact drift, the credential-editing flag has been verified in the enabled-by-default path, and the nav entries are still visible when the flag is off.

## Design Conflicts Discovered

- The only material decision here was whether to persist provider credentials in SQLite or keep them file-backed. The approved design keeps them in `data/secrets.toml`, which avoids an unnecessary migration and keeps the local-first boundary intact.
- Retry cannot be a generic "run it again" button. The plan resolves that by making retry an explicit allowlist in `backend/app/jobs/registry.py` and hiding the button everywhere else.
- The CSRF token is not a credential and must not be cached or persisted; the plan keeps it in memory only, bootstraps it through a no-store response, and sends it in a dedicated mutation header.
