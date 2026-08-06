# UltraQA page audit

## Goal and success criteria

- Goal: classify every user-facing page as working, failing, or explicitly blocked using live local evidence.
- Stop condition: all 14 route shapes have HTTP, prerequisite/API, and interaction-test evidence; adversarial scenarios are classified; temporary state is cleaned; the dev server is restored.
- Safety bounds: local data only; no secrets printed; no external-provider calls; no destructive mutations; browser-only claims remain blocked when direct browser control is unavailable.

## Scenario matrix

| ID | User/attacker model | Scenario | Command/harness | Expected signal | Actual result | Status | Evidence | Cleanup |
|---|---|---|---|---|---|---|---|---|
| PAGE-01 | Student | Dashboard `/` | live HTTP + page tests | 200 and interactive shell/course cards | HTTP 200; interaction regressions pass | PASS | curl 200; full frontend suite 732/732 | none |
| PAGE-02 | Student | Flashcards `/flashcards` | live HTTP + flashcard tests | 200, decks/empty state, generation recovery | HTTP 200; normal interactions pass; immediate 503 recovery message fails | FAIL (UX) | curl 200; full frontend suite; ADV-03 reproduction | none |
| PAGE-03 | Student | Jobs `/jobs` | live HTTP + jobs tests | 200, succeeded/failed jobs render | HTTP 200; succeeded and converter-failure records render | PASS | curl 200; `/api/jobs` 200; full frontend suite | none |
| PAGE-04 | Student | Review `/review` | live HTTP + review tests | 200, empty/due/new states | HTTP 200; current queue empty; state regressions pass | PASS | curl 200; review summary 200; full frontend suite | none |
| PAGE-05 | Student | Search `/search` | live HTTP + search tests | 200, empty/query/error states | HTTP 200; normal and hostile query handling pass | PASS | curl 200; full frontend suite; ADV-04 matrix | none |
| PAGE-06 | Student | Settings `/settings` | live HTTP + real save + settings tests | 200 and local credential mutation works safely | HTTP 200; real Save returned 403 | FAIL | server log: bootstrap 200 then PUT `/api/settings` 403 | no credential stored |
| PAGE-07 | Student | Tests index `/tests` | live HTTP + tests-page tests | 200 and empty/history states | HTTP 200; current list empty; state regressions pass | PASS | curl 200; course tests API 200 `[]`; full frontend suite | none |
| PAGE-08 | Student | Reader `/course/:courseId` | live HTTP + reader/PDF tests | 200 with valid 171-section PDF course | HTTP 200; PDF/source/lesson regressions pass | PASS | curl 200; course/sections APIs 200; full frontend suite | none |
| PAGE-09 | Student | Skills map `/course/:courseId/skills` | live HTTP + skills tests | 200 and correct empty state | HTTP 200; current graph empty; empty/error interactions pass | PASS (empty state) | curl 200; skills API 200 empty graph; full frontend suite | none |
| PAGE-10 | Instructor | Curriculum `/course/:courseId/curriculum` | live HTTP + curriculum tests | 200 and correct missing-curriculum state | HTTP 200; API 404 curriculum-not-found; guidance regressions pass | PASS (missing state) | curl 200; expected API 404; full frontend suite | none |
| PAGE-11 | Instructor | Diagnostics `/course/:courseId/diagnostics/validate` | live HTTP + diagnostics tests | 200 and missing-curriculum guidance | HTTP 200; missing-curriculum regressions pass | PASS | curl 200; full frontend suite | none |
| PAGE-12 | Student | Chapter test `/course/:courseId/chapter/:label/test` | live HTTP + chapter-test tests | 200, practice available, generation guarded | HTTP 200 with valid chapter label; interactions pass | PASS | curl 200; chapters API 200; full frontend suite | none |
| PAGE-13 | Student | Skill detail `/course/:courseId/skills/:skillId` | invalid-state live HTTP + detail tests | 200 shell with not-found/empty handling | HTTP 200 for invalid skill; tested states pass; no valid skill exists locally | PARTIAL (valid-data gap) | curl 200; skills graph empty; full frontend suite | none |
| PAGE-14 | Student | Test attempt `/course/:courseId/test/:attemptId` | invalid-state live HTTP + attempt tests | 200 shell with not-found handling | HTTP 200 for invalid attempt; interaction regressions pass; no valid attempt exists locally | PARTIAL (valid-data gap) | curl 200; tests list empty; full frontend suite | none |
| ADV-01 | Malformed navigator | Unknown route | `/definitely-not-a-route` | 404 | 404 | PASS | curl 404 | none |
| ADV-02 | Cross-origin local browser | Save Settings across dev ports | real browser request path | accepted with valid bootstrap token and permitted local origin | 403 | FAIL | `Origin localhost:3000` cannot equal API `Host localhost:8000` under current guard | none |
| ADV-03 | Missing-provider student | Start AI generation | observed flashcard/test POST | structured 503; no job created; actionable UI | backend structured 503; flashcard UI collapsed it to generic HTTP 503 | FAIL (UX) | readiness endpoint and server log | no job created |
| ADV-04 | Hostile search user | SQL/prompt-like/unicode query | API query matrix | bounded 200/422; no crash/leak | SQL-like, prompt-like, and Unicode queries returned 200; invalid bounds/filter/cursor returned 422 | PASS | live API matrix | none |
| ADV-05 | Repeated navigator | Repeat representative warm routes | repeated live HTTP | stable status, no server error | dashboard, settings, jobs, and reader stayed 200 at about 0.03-0.10 s after compilation | PASS | repeated curl matrix | none |
| ADV-06 | Stale client state | invalid persisted reader/workspace/search state | frontend regressions | safe fallback, no dead UI | regression suite passed | PASS (automated) | full frontend suite 732/732 | none |
| ADV-07 | Interrupted client | bounded unreachable API request | curl timeout probe | non-zero exit recognized, no false pass | unreachable port returned curl exit 7 | PASS | bounded curl to `127.0.0.1:65534` | none |
| ADV-08 | Maintainer | Dirty-worktree/debris check | git status before/after | only the QA evidence artifact is untracked | product tree unchanged; audit report is the only untracked artifact | PASS | `git status -sb` | retain report |
| ADV-09 | Maintainer | Full-suite contention/repeatability | full build, isolated reruns, full rerun | deterministic green suite | one keyboard-selection test timed out once during the full build, then passed 12/12 in three targeted reruns and the 732-test full rerun | FLAKY SIGNAL | `test-attempt.test.tsx`; fresh build and reruns | none |

## Commands run

- Live curl matrix: 14 user route shapes returned 200; unknown route returned 404.
- `rtk ./build.sh`: backend 743 passed and typecheck passed; one frontend test timed out under full-suite contention.
- Three isolated reruns of `test-attempt.test.tsx`: 12/12 tests passed each time.
- `rtk npm test -- --run`: full rerun passed, 94 files / 732 tests.
- `rtk npm run build`: passed; all 15 Next route entries built successfully.
- Hostile search matrix: valid adversarial inputs returned 200; malformed bounds/filter/cursor returned 422.

## Failures found

- `PAGE-06` / `ADV-02`: Settings writes fail in the documented two-port development topology because the server compares the entire Origin netloc to the API Host, including different ports.
- `ADV-03`: immediate AI-readiness failures return structured remediation from the backend, but flashcard entry points discard the response body and show only generic HTTP 503 text.
- `ADV-09`: a test-attempt keyboard-selection assertion timed out once in the full build but did not reproduce in three isolated runs or the full-suite rerun. This is a test reliability signal, not evidence that the page is currently broken.

## Fixes applied

- None. This is a read-only QA pass under principal-engineer review mode.

## Cleanup and rollback

- No generated app fixtures or product data mutations.
- Dev server restored with the readiness UI enabled; backend health and frontend root returned 200.
- UltraQA workflow state cleared after evidence capture.

## Residual risks

- Direct browser click/visual inspection is unavailable because the required in-app browser control surface is not exposed in this session.
- Skill-detail and test-attempt happy paths lack local valid data because the provider is unconfigured; interaction tests are the safe substitute.
- A current `convert_html` job failed because Docker is unavailable. The Jobs page handles this state; converter acceleration remains environment-dependent.

## Remediation completion

- `PAGE-06` / `ADV-02` resolved: trusted loopback frontend origins can perform CSRF-protected Settings mutations across the documented development ports, while unsafe origins remain rejected.
- `PAGE-02` / `ADV-03` resolved: immediate flashcard provider-readiness failures preserve structured remediation and route students to Settings instead of showing only HTTP 503.
- `ADV-09` resolved: quiz keyboard interactions now use awaited user events and passed repeated targeted runs plus the full suite.
- PDF-backed courses now open in Pages when no reader preference exists; explicit saved choices remain unchanged, including runtime fallback for non-PDF sources.
- Ollama selection now queries the backend-mediated local discovery route on provider selection/dropdown interaction, lists only current completion-capable models, preserves exact identifiers, and blocks a missing configured model with actionable repair copy.
- Live Ollama discovery returned six completion-capable models and excluded the installed embedding-only model.
- Final release gate: backend `798 passed`; frontend `94 files / 752 tests passed`; TypeScript, OpenAPI/client generation, and the Next.js production build passed.
- Final live smoke: backend health, Settings API/bootstrap, all static user routes, the real PDF-backed course reader, and its inline PDF endpoint returned successful responses.
- Whole-branch review and scoped re-review completed with no open code, security, or documentation findings.
