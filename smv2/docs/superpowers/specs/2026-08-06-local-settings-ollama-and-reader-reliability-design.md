# Local Settings, Ollama Discovery, and Reader Reliability Design

**Date:** 2026-08-06
**Status:** Approved for implementation
**Scope:** Close the user-facing failures found in the every-page audit, add safe Ollama model discovery, and make PDF Pages the correct first-open reader experience.

## Outcome

A student running SourceMind locally can configure Ollama from Settings, choose from the completion-capable models that are actually installed, save the configuration from the documented split-port development topology, and receive an actionable recovery message when a configured model is unavailable. AI generation failures preserve the backend remediation instead of collapsing to a generic HTTP status. PDF-backed courses open in Pages view on first use while explicit reader preferences remain stable.

## Problems being solved

1. Settings credential controls can be rendered disabled by a frontend build-time rollout flag even when the backend reports that local editing is writable.
2. Settings writes fail with HTTP 403 when the browser runs at `http://localhost:3000` and the API runs at `http://localhost:8000`, because the current CSRF origin check compares the complete `Origin` authority to the API `Host` authority.
3. Ollama uses a free-text model field and does not prove that the selected model is installed or completion-capable.
4. Immediate generation failures contain structured readiness/remediation data, but the flashcard entry points discard it and show only a generic HTTP 503 message.
5. A PDF-backed course does not reliably open in Pages view when the student has never selected a reader view.
6. A focus-sensitive test-attempt keyboard test timed out once under full-suite contention despite passing repeatedly in isolation and in the subsequent full-suite run.

## Scope

### Included

- Make local Settings editing depend on backend writability rather than a frontend build-time rollout flag.
- Repair the split-port local CSRF/origin contract without removing loopback or token protections.
- Add backend-mediated Ollama model discovery.
- Restrict interactive Ollama discovery and Settings persistence to loopback endpoints.
- Show only models currently installed and reporting the `completion` capability.
- Refresh discovery when Ollama becomes the selected provider and whenever the model dropdown is opened.
- Detect a configured model that is no longer installed and require an explicit replacement.
- Preserve structured immediate-generation failure messages and recovery actions.
- Default first-open PDF-backed courses to Pages view without overwriting saved preferences.
- Stabilize the flaky keyboard test by waiting for observable UI state, without changing product timing.

### Excluded

- Pulling, deleting, or updating Ollama models from SourceMind.
- Discovering or configuring remote/LAN Ollama servers through the Settings UI.
- Selecting an embedding model; the dropdown selects the completion model only.
- Automatically substituting the first available model.
- Persisting an Ollama model catalog or synchronizing it in the background.
- Changing generation job lifecycle semantics.
- Creating synthetic skill graphs or test attempts merely to expand manual QA data.

## Architectural decisions

### 1. Backend-mediated discovery

The browser does not call Ollama directly. A Settings-owned backend endpoint performs discovery so URL validation, timeouts, response limits, error normalization, and capability filtering live at one trusted boundary.

Discovery uses Ollama's local API in two stages:

1. `GET /api/tags` obtains the models currently installed.
2. `POST /api/show` with the model name obtains its capabilities.

Only models whose capabilities contain `completion` are returned. The result contains model identifiers needed by the dropdown, not raw manifests, templates, parameters, or filesystem metadata.

The endpoint is a `POST` because it accepts an unsaved base URL and causes a server-side network operation. It uses the same loopback-client, trusted-origin, JSON-content-type, and CSRF-token gate as Settings writes.

### 2. Strict loopback URL boundary

Interactive discovery accepts only the recommended local topology:

- scheme: `http`;
- host: `localhost`, `127.0.0.1`, or `[::1]` after canonical parsing;
- port: an explicit valid TCP port or Ollama's default `11434`;
- path: empty or `/`;
- no user information, query, or fragment;
- no redirects.

Ambiguous numeric, encoded, shortened, mapped, wildcard, link-local, private-LAN, and non-loopback host forms are rejected. The request uses bounded connect/read timeouts, a bounded response size, a bounded model count, and bounded capability-check concurrency.

Environment-level operator configuration remains an operator boundary. The interactive Settings surface does not broaden its URL allowlist to accommodate environment overrides.

### 3. Split-port Settings security contract

State-changing Settings requests retain all of these checks:

- the request client resolves to loopback;
- `Content-Type` is JSON;
- the in-memory CSRF token is present and correct;
- `Origin` is present, parseable, uses HTTP, has a loopback hostname, and exactly matches a configured trusted frontend origin after normalization;
- the API host itself is loopback-bound.

The origin is not required to use the API's port. This makes the documented `localhost:3000` frontend to `localhost:8000` API topology valid without accepting arbitrary origins. Missing, opaque, malformed, non-loopback, or unconfigured origins continue to fail closed.

The backend remains the authority for whether Settings is writable. The frontend build-time readiness flag no longer disables otherwise-writable controls.

### 4. Discovery response and model identity

The success response contains:

- a sorted, deduplicated list of current completion-capable model names;
- the currently configured model name, if any;
- whether the configured model is present in that returned list.

The dropdown value uses Ollama's canonical model identifier returned by the API. SourceMind does not rewrite tags or select aliases.

A successful response with zero eligible models is distinct from an unreachable Ollama server. Invalid local URLs, connection failures, invalid upstream JSON, response-limit violations, and upstream timeouts produce typed, redacted errors suitable for user-facing copy. Error responses do not include stack traces or raw upstream response bodies.

### 5. Settings interaction states

When the provider changes to Ollama, the form requests discovery. Opening the model dropdown requests a fresh discovery again. Concurrent duplicate requests are coalesced so a provider change followed immediately by an open action does not race two state updates.

The model control exposes these states:

- **Loading:** the control communicates that installed models are being checked.
- **Available:** only current completion-capable models are selectable.
- **Configured model missing:** no option is selected, Save is blocked, and the form displays: `Your configured Ollama model “<model>” is not installed. Install it in Ollama or select another available model.`
- **No installed models:** the form explains that Ollama has no installed models and directs the user to install one.
- **No completion-capable models:** the form explains that the installed models cannot be used for generation.
- **Connection failure:** the form explains that SourceMind could not reach Ollama at the local URL and offers a refresh action.
- **Invalid URL:** the form explains that only a local loopback Ollama URL is accepted.

The model dropdown contains only current API results. A missing configured model is never injected as a selectable option, and SourceMind never silently switches to the first model.

Changing the base URL invalidates the current discovery result and model selection until discovery succeeds for the new URL. Saving Ollama settings requires a currently available model.

### 6. Immediate generation recovery

The typed frontend API result preserves the structured backend error payload for requests that fail before a job is created. Flashcard generation entry points pass that payload to the shared error/recovery presentation instead of reconstructing an error from the HTTP status alone.

For missing credentials, an unavailable configured model, or an unreachable Ollama service, the UI shows the backend-safe remediation and a Settings action. Post-enqueue job failures continue to route to Jobs. No failed-preflight job is created.

### 7. First-open PDF reader behavior

Reader preference has three meaningful states: no stored choice, explicit Source/Lesson choice, and explicit Pages choice. The initial view is derived only when no stored choice exists:

- a course with a valid PDF Pages source opens in Pages;
- a course without a usable PDF Pages source opens in the existing non-Pages fallback;
- any explicit saved view remains authoritative.

The derived initial view is not written to local storage until the student explicitly changes the view. If a saved Pages preference later becomes unusable, the runtime falls back safely without deleting the preference.

### 8. Flaky test hardening

The product keyboard behavior is unchanged. The test waits for the actual interactive control to be ready and asserts the resulting checked state using observable DOM state. It does not add arbitrary sleeps, inflate global timeouts, or retry the whole test.

## Data flow

1. Settings loads the redacted settings document and an in-memory CSRF token.
2. The student selects Ollama or opens the model dropdown.
3. The frontend sends the current loopback base URL to the discovery endpoint with JSON content type and the CSRF header.
4. The backend validates the local request and URL before opening any connection.
5. The backend queries `/api/tags`, capability-checks the bounded model set with `/api/show`, filters to `completion`, and returns redacted model names plus configured-model availability.
6. The frontend reconciles the selection against the returned list. A missing configured model becomes an explicit invalid state, not an option.
7. Save submits only a model present in the latest successful discovery result. The backend independently validates the loopback URL and model selection contract before persistence.
8. Readiness and generation use the saved provider/model/base URL through the existing provider factory.

## Error and recovery contract

The backend uses stable categories rather than copy-dependent branching:

- `invalid_ollama_url`
- `ollama_unreachable`
- `ollama_timeout`
- `ollama_invalid_response`
- `ollama_response_too_large`
- `ollama_no_models`
- `ollama_no_completion_models`
- `ollama_model_unavailable`

Frontend copy may evolve, but routing depends on category. Provider-configuration categories route to Settings; failures belonging to an existing job route to Jobs.

## Security considerations

- Discovery is an SSRF-sensitive boundary. URL parsing and allowlisting happen before network I/O.
- Redirect following is disabled.
- Loopback checks use parsed/canonical host data, not string prefix or substring matching.
- Requests have strict time and body/model-count bounds.
- CSRF remains mandatory for Settings writes and discovery.
- CORS configuration is not treated as CSRF protection by itself.
- API keys, stored Ollama URLs, upstream response bodies, and stack traces remain absent from browser-visible settings responses and logs.
- Model names are rendered as text through React; no upstream HTML is interpreted.

## Compatibility and migration

- Existing Anthropic configuration remains unchanged.
- Existing valid Ollama configuration remains selected when its model appears in discovery.
- Existing missing Ollama configuration is not deleted automatically; the form requires an explicit repair before the next save.
- Existing environment-variable configuration continues to work outside the interactive Settings persistence path.
- No database migration is required.
- No new dependency is required; discovery reuses the existing HTTP client stack.

## Test strategy

### Backend

- Reproduce the current `localhost:3000` to `localhost:8000` Settings PUT failure, then prove the repaired trusted-loopback-origin behavior.
- Prove missing/wrong CSRF, missing/malformed/non-loopback/unconfigured Origin, non-JSON content, and non-loopback client requests remain rejected.
- Prove discovery rejects every disallowed URL form before network I/O.
- Prove redirects are not followed and timeout/response/model-count bounds are enforced.
- Prove `/api/tags` plus `/api/show` returns only deduplicated completion-capable current models.
- Prove malformed, empty, unreachable, timed-out, and oversized upstream responses produce the correct redacted category.
- Prove a missing configured model is reported unavailable.
- Prove Ollama Settings save rejects a model absent from a fresh validated discovery result or otherwise performs an equivalent backend-side availability check at save time.

### Frontend

- Prove Settings controls are enabled whenever the backend says editing is writable, independent of the removed frontend flag.
- Prove discovery runs when Ollama is selected and when the dropdown opens.
- Prove loading, available, empty, incompatible, unreachable, and invalid-URL states.
- Prove a missing configured model is absent from the options, shows the approved message, and blocks Save.
- Prove selecting an available model enables Save and submits the exact model identifier.
- Prove base-URL edits invalidate prior discovery.
- Prove structured immediate 503 failures show remediation and a Settings action in both flashcard entry points.
- Prove PDF first-open selection, saved Source/Lesson preservation, saved Pages preservation, and non-PDF fallback.
- Prove the focus-sensitive test-attempt behavior without arbitrary timing.

### Integration and release gates

- Backend targeted tests.
- Frontend targeted component and hook tests.
- Generated API schema refresh and drift check if the route schema changes.
- Full backend suite.
- Full frontend suite, including repeated execution of the formerly flaky test file.
- Frontend typecheck and production build.
- Local smoke: Settings bootstrap, Ollama discovery against a reachable local daemon when available, split-port Settings save, unavailable-model message, flashcard preflight recovery, and first-open PDF Pages behavior.

## Acceptance criteria

- Settings is interactive in the normal local launch without requiring a hidden frontend flag.
- A valid CSRF-protected Settings save from the configured loopback frontend origin succeeds across ports; unsafe origins still fail.
- Selecting Ollama or opening its model dropdown triggers backend-mediated discovery.
- The dropdown contains only currently installed completion-capable models.
- A missing configured model produces the approved actionable message and cannot be saved until repaired.
- SourceMind never silently selects another model.
- Immediate provider failures show the remediation and Settings route instead of only `HTTP 503`.
- A first-open PDF-backed course uses Pages; saved reader choices remain unchanged.
- Targeted and full verification gates pass without relying on retries or increased global timeouts.
