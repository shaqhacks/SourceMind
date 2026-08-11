# Local Settings, Ollama, and Reader Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local Settings writable and secure, discover only currently installed completion-capable Ollama models, preserve actionable generation failures, open first-use PDF courses in Pages view, and eliminate the observed keyboard-test flake.

**Architecture:** Settings remains a backend-owned security boundary: trusted loopback origins plus CSRF protect writes and a new POST discovery route. A focused async Ollama discovery service validates and pins loopback URLs, bounds upstream work, calls `/api/tags` then `/api/show`, and returns a redacted typed catalog. The frontend consumes the generated OpenAPI contract, reconciles the saved model against live results without silent fallback, routes immediate readiness failures through the existing recovery UI, and distinguishes an absent reader preference from an explicit Source choice.

**Tech Stack:** FastAPI, Pydantic, httpx, pytest, Next.js 16, React 19, TypeScript, openapi-fetch, Testing Library, Vitest.

## Global Constraints

- Use strict TDD for every behavior change: write one focused test, run it to see the expected failure, then write the minimum implementation and rerun it green.
- Do not add dependencies.
- Interactive Ollama URLs are HTTP loopback only: `localhost`, `127.0.0.1`, or `[::1]`, normalized to a pinned literal address with port `11434` when omitted.
- Do not follow redirects. Bound response bodies to 1 MiB, listed models to 100, capability concurrency to 4, connect timeout to 1 second, and total/read timeout to 5 seconds.
- Discovery returns only current model identifiers whose `/api/show` capabilities contain `completion`; it never inserts a missing configured model and never auto-selects the first model.
- Settings discovery and mutations require loopback client access, configured trusted loopback Origin, JSON content type, and the existing `X-CSRF-Token`.
- Browser-visible responses remain redacted: no stored credential values, stored Ollama URL, raw upstream body, stack trace, template, parameters, or model filesystem metadata.
- The exact missing-model copy is: `Your configured Ollama model “<model>” is not installed. Install it in Ollama or select another available model.`
- Generated artifacts `openapi.json` and `frontend/lib/api/schema.d.ts` are regenerated, never hand-edited.
- Existing Anthropic behavior, job lifecycle, and explicit reader preferences remain unchanged.
- No arbitrary sleeps, global timeout inflation, whole-test retries, or silent fallback logic.

---

## File structure

- `backend/app/security/local_settings.py`: validates local client, trusted loopback Origin, JSON, CSRF, and canonical loopback Ollama URLs.
- `backend/app/services/ollama_discovery_service.py`: bounded async `/api/tags` and `/api/show` orchestration plus typed domain failures.
- `backend/app/routers/settings.py`: Settings CRUD and the new discovery route; validates Ollama availability before persistence.
- `backend/app/schemas.py`: discovery request and response schemas.
- `backend/tests/test_settings_security.py`: cross-port trusted-origin and rejection regressions.
- `backend/tests/test_ollama_discovery.py`: discovery service/route contract, bounds, redaction, and save validation.
- `backend/tests/test_settings_api.py`: persisted Settings compatibility.
- `openapi.json` and `frontend/lib/api/schema.d.ts`: generated API contract.
- `frontend/lib/api/client.ts`: typed discovery helper.
- `frontend/components/settings/SettingsForm.tsx`: provider-aware model controls and discovery state machine.
- `frontend/__tests__/settings-page.test.tsx`: enablement, discovery, reconciliation, errors, and save behavior.
- `frontend/lib/api/errors.ts`: safe extraction of structured FastAPI detail.
- `frontend/components/reader/CardsCTA.tsx` and `frontend/components/flashcards/ChapterDeckCard.tsx`: immediate generation recovery.
- `frontend/lib/hooks/useReaderView.ts` and `frontend/components/reader/CourseReader.tsx`: nullable preference and first-open Pages derivation.
- `frontend/__tests__/test-attempt.test.tsx`: keyboard harness stabilization only.

---

### Task 1: Repair the local Settings security boundary

**Files:**
- Modify: `backend/app/security/local_settings.py`
- Modify: `backend/tests/test_settings_security.py`

**Interfaces:**
- Consumes: `app.config.cors_origins()` and the existing per-process `csrf_token()`.
- Produces: `require_local_settings_write(request: Request) -> None` accepting the documented split-port trusted loopback origin; `normalize_ollama_base_url(value: str) -> str` for Task 2.

- [ ] **Step 1: Write the failing cross-port and content-type tests**

Add a route regression that sends `Origin: http://localhost:3000`, `Host: localhost:8000`, the real CSRF header, and `SMV2_CORS_ORIGINS=http://localhost:3000`; expect 200. Add separate 403 cases for missing Origin, `Origin: null`, an unconfigured loopback port, HTTPS/non-loopback Origin, missing JSON content type, and a non-loopback API Host.

```python
def test_settings_write_accepts_configured_loopback_origin_across_ports(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://localhost:3000")
    token = client.get("/api/settings/bootstrap").json()["csrf_token"]
    response = client.put(
        "/api/settings",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers={
            "X-CSRF-Token": token,
            "Origin": "http://localhost:3000",
            "Host": "localhost:8000",
        },
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run the security slice and confirm RED**

```bash
cd backend
uv run pytest -q tests/test_settings_security.py
```

Expected: the cross-port test fails with HTTP 403 from `origin must match request host`; new missing-guard tests fail behaviorally, not from fixture errors.

- [ ] **Step 3: Implement normalized trusted-origin validation**

Keep the guard order loopback client → JSON content type → configured trusted loopback Origin → constant-time CSRF. Do not accept Referer as an Origin substitute.

```python
def require_local_settings_write(request: Request) -> None:
    _require_loopback(request)
    _require_json(request)
    _require_trusted_loopback_origin(request)
    supplied = request.headers.get(CSRF_HEADER_NAME)
    if not supplied or not secrets.compare_digest(supplied, _CSRF_TOKEN):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid")
```

Compare normalized `(scheme, hostname, effective_port)` tuples against `config.cors_origins()`. Separately require the API Host hostname to be loopback. Retain `testserver` only as a TestClient loopback sentinel.

- [ ] **Step 4: Add URL-normalization tests and implementation**

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost", "http://127.0.0.1:11434"),
        ("http://localhost:11434/", "http://127.0.0.1:11434"),
        ("http://127.0.0.1:11435", "http://127.0.0.1:11435"),
        ("http://[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_normalize_ollama_base_url_accepts_only_canonical_loopback(raw, expected):
    assert normalize_ollama_base_url(raw) == expected
```

Reject HTTPS, credentials, query, fragment, non-root path, `127.1`, decimal/octal/hex IP forms, IPv4-mapped IPv6, `0.0.0.0`, `[::]`, link-local, private-LAN, public, and malformed ports. The domain exception must not echo the raw URL.

- [ ] **Step 5: Run the security slice GREEN**

```bash
cd backend
uv run pytest -q tests/test_settings_security.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/security/local_settings.py backend/tests/test_settings_security.py
git commit -m "fix(settings): allow trusted loopback origins across ports"
```

---

### Task 2: Add bounded backend Ollama discovery and save validation

**Files:**
- Create: `backend/app/services/ollama_discovery_service.py`
- Create: `backend/tests/test_ollama_discovery.py`
- Modify: `backend/app/routers/settings.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_settings_api.py`

**Interfaces:**
- Consumes: `normalize_ollama_base_url`, `require_local_settings_write`, `config.ollama_base_url()`, and local-settings persistence.
- Produces: `async discover_ollama_models(base_url: str) -> list[str]`, `POST /api/settings/ollama/models`, `OllamaModelsDiscoverIn`, and `OllamaModelsDiscoverOut`.

- [ ] **Step 1: Write failing service tests**

Use `httpx.MockTransport` injected through a `transport` parameter. `/api/tags` must include duplicates and completion/embedding-only candidates; `/api/show` returns literal capability arrays. Assert case-insensitive sorted, deduplicated completion models only.

```python
models = await discover_ollama_models(
    "http://127.0.0.1:11434",
    transport=transport,
)
assert models == ["gemma3:4b", "llama3.2:latest"]
```

- [ ] **Step 2: Run the service test RED**

```bash
cd backend
uv run pytest -q tests/test_ollama_discovery.py -k service
```

Expected: import/collection fails because the service does not exist.

- [ ] **Step 3: Implement the minimal async discovery service**

```python
class OllamaDiscoveryError(RuntimeError):
    def __init__(self, category: str, message: str, *, status_code: int):
        super().__init__(message)
        self.category = category
        self.status_code = status_code
```

Implement `discover_ollama_models(base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> list[str]`. Use one `httpx.AsyncClient(follow_redirects=False)`. Read responses through a 1 MiB limited-byte helper before JSON decoding, reject more than 100 tag entries, and run `/api/show` checks through `asyncio.Semaphore(4)`. A malformed show response is `ollama_invalid_response`, not compatible.

- [ ] **Step 4: Add failing bounds/error tests**

Cover redirects, connect errors, timeouts, invalid JSON, oversized tag/show bodies, more than 100 tags, malformed entries, empty models, and zero completion models. Assert only stable category/safe message and no raw body/path leakage.

```python
with pytest.raises(OllamaDiscoveryError) as exc_info:
    await discover_ollama_models("http://127.0.0.1:11434", transport=transport)
assert exc_info.value.category == "ollama_invalid_response"
assert "upstream-secret" not in str(exc_info.value)
```

- [ ] **Step 5: Run service tests GREEN**

```bash
cd backend
uv run pytest -q tests/test_ollama_discovery.py -k service
```

- [ ] **Step 6: Write failing route-contract tests**

Add exact schemas:

```python
class OllamaModelsDiscoverIn(BaseModel):
    base_url: str | None = Field(default=None, max_length=2048)
    configured_model: str | None = Field(default=None, min_length=1, max_length=200)

class OllamaModelsDiscoverOut(BaseModel):
    models: list[str]
    configured_model: str | None
    configured_model_available: bool
```

POST with real CSRF/trusted-origin headers. Mock discovery to return `["llama3.2:latest"]`; assert a missing configured model stays absent and availability is false. Missing CSRF must fail before service invocation.

- [ ] **Step 7: Implement route and typed error mapping**

Resolve a nonblank request URL, otherwise `config.ollama_base_url()`, then normalize. Map domain errors to redacted detail `{code, failure_category, message, remediation}`: HTTP 400 invalid URL, 503 unreachable/timeout/empty capability states, and 502 invalid/oversized upstream responses.

- [ ] **Step 8: Write failing save-validation tests**

PUT Ollama settings with a model missing from discovery. Expect HTTP 409, `failure_category == "ollama_model_unavailable"`, and no local/secrets file mutation. Add a passing case where discovery includes the exact model and persistence retains redaction.

- [ ] **Step 9: Implement save-time validation**

Convert `update_settings` to `async def`. For Ollama, normalize submitted or existing URL, call the same discovery service, and require exact model membership before writing either settings file. Persist the normalized URL only after validation. Anthropic bypasses discovery.

- [ ] **Step 10: Run backend slice GREEN**

```bash
cd backend
uv run pytest -q tests/test_settings_security.py tests/test_settings_api.py tests/test_ollama_discovery.py
```

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/ollama_discovery_service.py backend/app/routers/settings.py backend/app/schemas.py backend/tests/test_ollama_discovery.py backend/tests/test_settings_api.py
git commit -m "feat(settings): discover local Ollama models"
```

---

### Task 3: Regenerate the API contract and add the client helper

**Files:**
- Modify (generated): `openapi.json`
- Modify (generated): `frontend/lib/api/schema.d.ts`
- Modify: `frontend/lib/api/client.ts`
- Modify: `frontend/__tests__/settings-page.test.tsx`

**Interfaces:**
- Consumes: Task 2's discovery route.
- Produces: generated discovery types and `discoverOllamaModels(body)`.

- [ ] **Step 1: Regenerate committed artifacts**

```bash
cd backend
uv run python -m app.export_openapi ../openapi.json
cd ../frontend
npm run gen:api
```

Inspect the diff: only the discovery path/schemas and direct generated metadata may change.

- [ ] **Step 2: Write a failing CSRF client test**

Extend the existing Settings CSRF test:

```typescript
await api.discoverOllamaModels({
  base_url: "http://localhost:11434",
  configured_model: "llama3.2:latest",
});
```

Assert POST `/api/settings/ollama/models`, cached `X-CSRF-Token`, and the exact request fields.

- [ ] **Step 3: Run RED**

```bash
cd frontend
npm test -- --run __tests__/settings-page.test.tsx
```

- [ ] **Step 4: Add generated aliases and helper**

```typescript
export type OllamaModelsDiscoverIn = components["schemas"]["OllamaModelsDiscoverIn"];
export type OllamaModelsDiscoverOut = components["schemas"]["OllamaModelsDiscoverOut"];

export async function discoverOllamaModels(
  body: OllamaModelsDiscoverIn,
): Promise<ApiResult<OllamaModelsDiscoverOut>> {
  return request(client.POST("/api/settings/ollama/models", {
    headers: await csrfHeaders(),
    body,
  }));
}
```

- [ ] **Step 5: Run GREEN**

```bash
cd frontend
npm test -- --run __tests__/settings-page.test.tsx
npm run typecheck
```

- [ ] **Step 6: Commit**

```bash
git add openapi.json frontend/lib/api/schema.d.ts frontend/lib/api/client.ts frontend/__tests__/settings-page.test.tsx
git commit -m "feat(settings): expose Ollama discovery client"
```

---

### Task 4: Build the Ollama dropdown and restore Settings interactivity

**Files:**
- Modify: `frontend/components/settings/SettingsForm.tsx`
- Modify: `frontend/__tests__/settings-page.test.tsx`

**Interfaces:**
- Consumes: `discoverOllamaModels`, `SettingsOut`, and the approved missing-model copy.
- Produces: free-text Anthropic model control and live native Ollama select.

- [ ] **Step 1: Replace the rollout-disabled test**

Remove the build-time flag assertion. With the environment variable absent and backend rollout true, expect provider, API key, base URL, and Save controls enabled.

- [ ] **Step 2: Add failing trigger/coalescing tests**

Assert switching to Ollama discovers with first-time URL `http://localhost:11434`. `pointerDown` on the Ollama select refreshes after the first request. Two triggers while one promise is pending produce one in-flight call.

- [ ] **Step 3: Add failing reconciliation/error tests**

With:

```typescript
const discovered = {
  models: ["gemma3:4b", "llama3.2:latest"],
  configured_model: "missing:latest",
  configured_model_available: false,
};
```

assert the missing model is not an option, selection is blank, Save is disabled, and exact approved copy is visible. Separately cover zero models, no completion models, invalid URL, timeout/unreachable, and malformed response. Raw upstream bodies must never render.

- [ ] **Step 4: Run RED**

```bash
cd frontend
npm test -- --run __tests__/settings-page.test.tsx
```

- [ ] **Step 5: Implement the minimal state machine**

`editingEnabled` uses only backend rollout. Add:

```typescript
type OllamaDiscoveryState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "loaded"; models: string[]; configuredModelAvailable: boolean }
  | { kind: "error"; category: string | null; message: string };
```

Keep one in-flight promise ref and a monotonically increasing request id for stale responses. Switching from Anthropic clears its model, sets the default URL only for first-time Ollama, and refreshes. Base URL edits clear model/discovery. Use a native select with `onPointerDown` refresh and only returned options.

- [ ] **Step 6: Implement save gating**

For Ollama, Save requires loaded discovery and selected model membership. Submit a first-time/edited URL; otherwise retain the stored redacted URL server-side. Never auto-select the first model.

- [ ] **Step 7: Run GREEN**

```bash
cd frontend
npm test -- --run __tests__/settings-page.test.tsx
npm run typecheck
```

- [ ] **Step 8: Commit**

```bash
git add frontend/components/settings/SettingsForm.tsx frontend/__tests__/settings-page.test.tsx
git commit -m "feat(settings): select installed Ollama models"
```

---

### Task 5: Preserve structured immediate generation recovery

**Files:**
- Modify: `frontend/lib/api/errors.ts`
- Modify: `frontend/components/reader/CardsCTA.tsx`
- Modify: `frontend/components/flashcards/ChapterDeckCard.tsx`
- Modify: `frontend/__tests__/cards-cta.test.tsx`
- Modify: `frontend/__tests__/chapter-deck-card.test.tsx`

**Interfaces:**
- Consumes: FastAPI `{detail:{code,failure_category,message,remediation}}` in `ApiResult.error`.
- Produces: `apiErrorDetail(error: unknown): ApiErrorDetail | null` and immediate `RecoveryBanner`.

- [ ] **Step 1: Write failing reader CTA test**

Return status 503 plus full structured detail. After Generate, assert alert text `LLM provider is not ready`, Settings link present, retry absent, and no job/EventSource created.

```typescript
mockedGenerateCards.mockResolvedValue({
  status: 503,
  ok: false,
  error: {
  detail: {
    code: "llm_readiness_unavailable",
    failure_category: "missing_credentials",
    message: "LLM provider is not ready",
    remediation: "Configure an available model in Settings.",
  },
  },
});
```

- [ ] **Step 2: Write failing chapter tests**

Cover both the initial section failure and a later queued-section failure. Both must show Settings recovery rather than `HTTP 503`.

- [ ] **Step 3: Run RED**

```bash
cd frontend
npm test -- --run __tests__/cards-cta.test.tsx __tests__/chapter-deck-card.test.tsx
```

- [ ] **Step 4: Implement safe detail extraction**

Import `ApiErrorDetail` as a type. Export a structural parser allowing only string/null values for the four safe fields. `describeError` prefers safe structured message/remediation once, while retaining unsupported-format and network behavior.

```typescript
function optionalString(value: unknown): string | null | undefined {
  return value === null || typeof value === "string" ? value : undefined;
}

export function apiErrorDetail(error: unknown): ApiErrorDetail | null {
  if (!error || typeof error !== "object" || !("detail" in error)) return null;
  const detail = (error as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const candidate = detail as Record<string, unknown>;
  const code = optionalString(candidate.code);
  const failureCategory = optionalString(candidate.failure_category);
  const message = optionalString(candidate.message);
  const remediation = optionalString(candidate.remediation);
  if (
    code === undefined ||
    failureCategory === undefined ||
    message === undefined ||
    remediation === undefined
  ) return null;
  return { code, failure_category: failureCategory, message, remediation };
}
```

- [ ] **Step 5: Render recovery state**

In both components store `{message, detail}`, pass `error` to the parser, and render `RecoveryBanner` with no job id. Preserve 409 resync and post-job Jobs behavior.

- [ ] **Step 6: Run GREEN and commit**

```bash
cd frontend
npm test -- --run __tests__/cards-cta.test.tsx __tests__/chapter-deck-card.test.tsx
npm run typecheck
git add lib/api/errors.ts components/reader/CardsCTA.tsx components/flashcards/ChapterDeckCard.tsx __tests__/cards-cta.test.tsx __tests__/chapter-deck-card.test.tsx
git commit -m "fix(flashcards): preserve provider recovery details"
```

---

### Task 6: Default first-open PDF courses to Pages

**Files:**
- Modify: `frontend/lib/hooks/useReaderView.ts`
- Modify: `frontend/components/reader/CourseReader.tsx`
- Modify: `frontend/__tests__/course-reader.test.tsx`

**Interfaces:**
- Consumes: `hasPdfPageProvenance(activeSection)` and `smv2.readerView.<courseId>`.
- Produces: `storedMode: ViewMode | null`; null means no explicit choice.

- [ ] **Step 1: Write four failing regressions**

Cover no storage + PDF → Pages; saved Source + PDF → Source; saved Pages + PDF → Pages; no storage + text → Source. Assert derived Pages does not write storage until explicit user change.

- [ ] **Step 2: Run RED**

```bash
cd frontend
npm test -- --run __tests__/course-reader.test.tsx
```

- [ ] **Step 3: Make preference absence explicit**

```typescript
export interface UseReaderViewResult {
  storedMode: ViewMode | null;
  setStoredMode: (mode: ViewMode) => void;
}
```

`readStoredMode` and server snapshot return null for missing/invalid/inaccessible storage. Preserve best-effort persistence.

- [ ] **Step 4: Derive runtime mode**

```typescript
const preferredMode: ViewMode = storedMode ?? (pagesAvailable ? "pages" : "source");
const mode: ViewMode =
  preferredMode === "pages" && !pagesAvailable ? "source" : preferredMode;
```

Do not persist during initialization or fallback.

- [ ] **Step 5: Run GREEN and commit**

```bash
cd frontend
npm test -- --run __tests__/course-reader.test.tsx __tests__/course-reader-client.test.tsx
npm run typecheck
git add lib/hooks/useReaderView.ts components/reader/CourseReader.tsx __tests__/course-reader.test.tsx
git commit -m "fix(reader): open PDF courses in Pages first"
```

---

### Task 7: Stabilize the keyboard test harness

**Files:**
- Modify: `frontend/__tests__/test-attempt.test.tsx`

**Interfaces:**
- Consumes: existing window-level numeric/Enter behavior.
- Produces: awaited user interactions; no product change.

- [ ] **Step 1: Run five focused repetitions**

```bash
cd frontend
for run in 1 2 3 4 5; do npm test -- --run __tests__/test-attempt.test.tsx || exit 1; done
```

Record whether the flake reproduces; no reproduction does not justify product changes.

- [ ] **Step 2: Replace synchronous keyboard helpers**

Import `userEvent`; pass a user instance to helpers and await keys. Keep assertions on real checked state and next question. Do not add sleeps/timeouts.

```typescript
async function advanceFirstQuestionByKeyboard(user: ReturnType<typeof userEvent.setup>) {
  await user.keyboard("2");
  await waitFor(() => expect(screen.getByRole("radio", { name: "4" })).toBeChecked());
  await user.keyboard("{Enter}");
  await screen.findByText("Capital of France?");
}
```

- [ ] **Step 3: Run five repetitions GREEN and commit**

```bash
cd frontend
for run in 1 2 3 4 5; do npm test -- --run __tests__/test-attempt.test.tsx || exit 1; done
git add __tests__/test-attempt.test.tsx
git commit -m "test(frontend): stabilize quiz keyboard interactions"
```

---

### Task 8: Run integration and release gates

**Files:**
- Verify all Task 1–7 files.
- Modify generated artifacts only if the full build reveals expected schema drift.

- [ ] **Step 1: Stop the dedicated dev server**

Stop only SourceMind's current dev session before building. Confirm ports 3000/8000 are no longer owned by that session.

- [ ] **Step 2: Run targeted backend verification**

```bash
cd backend
uv run pytest -q tests/test_settings_security.py tests/test_settings_api.py tests/test_ollama_discovery.py tests/test_cards_generation.py
```

- [ ] **Step 3: Run targeted frontend verification**

```bash
cd frontend
npm test -- --run __tests__/settings-page.test.tsx __tests__/cards-cta.test.tsx __tests__/chapter-deck-card.test.tsx __tests__/course-reader.test.tsx __tests__/course-reader-client.test.tsx __tests__/test-attempt.test.tsx
npm run typecheck
```

- [ ] **Step 4: Run the full gate**

```bash
cd ..
./build.sh
```

Expected: backend compile/tests, OpenAPI export, generated client, typecheck, all frontend tests, and production build pass.

- [ ] **Step 5: Run security/static checks**

```bash
rg -n "follow_redirects=True|dangerouslySetInnerHTML|console\.(log|debug)|NEXT_PUBLIC_.*(KEY|TOKEN|SECRET)" backend/app frontend --glob '!frontend/lib/api/schema.d.ts'
git diff --check
```

No new unsafe redirect, secret exposure, debug logging, or whitespace errors.

- [ ] **Step 6: Restore and smoke locally**

Start `./dev.sh`. Verify backend `/health` and frontend `/` return 200. With Ollama present, verify only current completion models. Without it, verify the unreachable message. Verify missing model blocks Save, split-port Save succeeds for an available model, flashcard preflight links Settings, and first-open PDF uses Pages.

- [ ] **Step 7: Record final state**

```bash
git status -sb
git log --oneline --decorate -12
```

Only the retained `ultraqa-every-page/` audit artifact may remain untracked; no implementation file may be unstaged.
