# Student Experience Remediation Design

**Date:** 2026-08-05

**Status:** Draft for user review; implementation plans pending

## Context

SourceMind's automated coverage and core local runtime are healthy, but a student-perspective audit found several gaps that tests do not currently protect against:

- AI-backed actions can repeatedly fail when no provider is configured, with technical recovery text and no guided setup or job history surface.
- Study recommendations count unreviewed cards as "due," while review summaries correctly report them as "new."
- The dashboard infers sample-course identity from course count and status, so a sole user-created course can receive the sample-course hint.
- Instructor and research controls appear beside learner actions in the primary navigation.
- Large courses have no deterministic course-content search, and the application shell is only lightly responsive.
- Imports accept PDFs only.
- The current local-only product has no accounts or cross-device sync. That remains a deliberate boundary rather than part of this remediation.

This design addresses the student-facing gaps while preserving SourceMind's local-first, single-user architecture and the existing deterministic-before-generative rule.

## Goals

1. Make every AI-dependent action fail early with understandable, actionable recovery.
2. Give all review and recommendation surfaces one consistent definition of overdue, new, and available work.
3. Identify sample data explicitly rather than through UI heuristics.
4. Separate learner workflows from instructor/research workflows without implying a security boundary.
5. Make a large local course discoverable without an LLM or network connection.
6. Support the dashboard, reader, review, flashcards, tests, and upload flows on phone, tablet, and desktop layouts.
7. Generalize ingestion so additional local document formats can enter the same durable course pipeline.
8. Deliver the work in independently reviewable, reversible phases with regression coverage before behavioral changes.

## Non-goals

- Remote authentication, multi-tenant authorization, cloud storage, or cross-device synchronization.
- Turning Learner/Instructor mode into an access-control mechanism.
- Replacing the existing job system, generated API client, content-addressed section identity, or SQLite persistence model.
- Requiring an LLM for search, import, reading, notes, highlights, or source-content navigation.
- Adding analytics or telemetry that leave the local machine.
- Supporting arbitrary proprietary document formats in the first import expansion.

## Architectural approach

The work is divided into five implementation programs, ordered by user risk:

1. AI readiness and recovery.
2. Review/sample correctness.
3. Learner and Instructor workspace modes.
4. Search and responsive navigation.
5. Import adapters and generalized source locations.

Each program produces working, independently testable software. Correctness and recovery ship before new feature breadth. Cross-program interfaces are intentionally small: AI readiness exposes a typed capability contract; review availability exposes one shared service result; workspace mode remains a UI preference; search exposes a typed local query API; import adapters emit one normalized source-document representation.

## Program 1: AI readiness and recovery

### Capability contract

Add a provider-capability service as the only authority for whether AI-backed actions may start. It returns a typed status with:

- selected provider and model;
- configuration state: `not_configured`, `configured_unverified`, `ready`, or `unreachable`;
- supported capabilities: chat, lesson generation, cards, tests, and practice extraction;
- last connection-check time and a sanitized failure category;
- remediation instructions intended for the UI;
- no API keys, tokens, raw provider responses, filesystem paths, or secret fragments.

`GET /api/llm/status` reads configuration without making a network call. `POST /api/llm/status/check` performs an explicit provider-specific connectivity check. Connectivity checks are never triggered on ordinary page load, never generate learning content, and never create ledger cost entries unless the provider has no non-billable verification operation; in that case the result remains `configured_unverified` and the UI says so.

Every generation router calls the capability service before creating a job. An unavailable capability returns a typed 409 response with a stable error code such as `llm_not_configured` or `llm_unreachable`. The frontend maps these codes to setup actions rather than treating them as generic retryable failures.

### Local settings

Add a `/settings` surface with provider selection, model selection, readiness state, connection testing, and local-only credential setup.

Credential writes have the following invariants:

- The backend accepts them only from a loopback client and a same-origin JSON request carrying a per-process CSRF token.
- Secrets are written atomically to `data/secrets.toml` with owner-only permissions.
- Existing secrets are never returned to the browser; the UI receives only `configured: true|false`.
- Secrets never enter logs, job payloads, error details, API schemas, test snapshots, or LLM usage records.
- Clearing a credential requires an explicit confirmation and affects only the selected provider.

If the deployment is not bound to loopback, credential editing is disabled and Settings displays filesystem/environment instructions instead. Ollama setup remains credential-free and reports whether the configured local endpoint is reachable.

### Jobs and recovery

Add a `/jobs` surface showing active and recent jobs, grouped by course and type. It provides human-readable status, progress, sanitized failure reason, related course/section navigation, and a retry action only when the job type has an idempotent retry contract. It does not allow arbitrary job creation or deletion.

Generation surfaces link provider failures to Settings and other failures to the relevant Jobs entry. Retry is disabled while the underlying capability remains unavailable. Source text and existing generated material remain usable throughout.

### Acceptance criteria

- A fresh installation with no provider configured can upload, read, search, annotate, export, and review existing cards without seeing a raw environment-variable error.
- Clicking an AI action while unconfigured creates no job and presents a Settings action.
- A configured provider can be explicitly checked without generating course content.
- Failed historical jobs remain inspectable and do not block current course use.
- No API response or log reveals a stored credential.

## Program 2: review and sample correctness

### Canonical review availability

Create one review-availability service used by review summary, review queue, study recommendations, adaptive-study assembly, and chat context. Its result separates:

- `overdue_count`: cards with a learner-scoped review state whose `due_at` is at or before now;
- `new_count`: cards with no learner-scoped review state;
- `available_count`: `overdue_count + new_count`;
- `total_count`: all cards in the requested scope.

The service accepts course scope and optional section scope, plus learner identity and evaluation time. Tests pass an explicit clock. No consumer reimplements joins or the meaning of these counts.

Study recommendations use separate reasons:

- `due_cards` only when `overdue_count` reaches the existing backlog threshold;
- `new_cards` when new material is available but there is no overdue backlog;
- mixed availability reports both values and prioritizes the overdue wording.

Chat copy uses "overdue" and "new" precisely. Review-session entry points may still include both categories, but the chooser and action label state what the session contains.

### Explicit sample identity

Add a non-null `Course.is_sample` boolean with a default of false. The bundled seed path is the only creation path that sets it true. API course responses include the field, and the dashboard hint depends on that field rather than course count, title, or status.

For existing installations, startup reconciliation reads the existing `sample_seeded` marker's recorded course identifier and marks that course as the sample when it still exists. No title-based migration occurs. Deleting the sample never causes a later user-created course to inherit sample status.

### Acceptance criteria

- The live-data case `0 overdue / 7 new` is reported consistently by review summary, recommendations, review chooser, and chat.
- New cards are never described as overdue or "piling up."
- A sole user-created ready course never receives the sample hint.
- The seeded course receives the hint until dismissed, even when additional user courses exist; the hint is attached to the sample course rather than to an incidental course count.
- Learner scoping remains intact for all review counts.

## Program 3: Learner and Instructor workspace modes

### Mode model

Add a persisted UI preference with two values: `learner` and `instructor`. The default is `learner`. The preference follows the existing local preference pattern and is not stored as authorization data.

The header's decorative avatar becomes a workspace-mode menu. Switching into Instructor mode requires a one-time explanation that the mode exposes curriculum, evidence-mapping, diagnostic-validation, and research controls. Switching back is immediate.

### Navigation and route behavior

Learner mode includes Home, reader, review, flashcards, tests, skill map, notes, highlights, search, Jobs, and Settings. It omits curriculum editing, diagnostic validation, retention-study administration, and other research controls from navigation.

Instructor mode adds a distinct "Instructor tools" navigation group. State-changing buttons use explicit verbs and confirmation where publication or irreversible evidence decisions are involved.

Direct navigation to an instructor route while in Learner mode renders an explanatory boundary with "Switch to Instructor mode" and "Back to course" actions. The route does not silently change mode. Backend endpoints remain unchanged because this mode is not a security boundary; any future remote deployment still requires real authorization.

### Acceptance criteria

- A first-run student sees no instructor/research controls.
- Instructor tools remain reachable after an intentional mode switch.
- Direct links do not bypass the learner-mode explanation.
- Mode switching is fully keyboard accessible and persists across reloads.
- Product copy never claims that workspace mode protects data or identifies a real user role.

## Program 4: deterministic search and responsive navigation

### Search index

Add a contentless SQLite FTS5 index with one row per searchable document. Indexed document types are:

- extracted source section;
- generated lesson when present;
- student note;
- highlight note when present.

Each row stores unindexed identifiers for course, document type, source record, section, asset, and source locator. Indexed fields are title and body text. Search-index writes occur in the same transaction as the content mutation that requires them. Ingest and re-ingest replace affected section rows, lesson generation replaces the lesson row, and note/highlight changes upsert or delete their rows.

Startup verifies FTS5 availability. When unavailable, the API uses a deterministic escaped `LIKE` fallback over the same source tables. The fallback is functionally equivalent but may be slower; it is surfaced as a capability detail, not an error.

Provide a rebuild command and service operation that recreate the index from canonical tables without changing user data. Search data is derived and participates in the existing derived-data registry/re-ingest rules.

### Search API and UI

`GET /api/courses/{course_id}/search` accepts a non-empty query, document-type filters, and a bounded cursor. Results include title, sanitized excerpt, document type, section identifier, and structured source locator. Ranking uses FTS5 rank plus an exact-title boost; it does not use embeddings or an LLM.

The reader exposes course search from its top bar and keyboard shortcut. Results open the relevant section and locator. A global command palette initially provides navigation and common local actions; it calls the same course-search API only when a course is active.

### Responsive shell

Support these layout bands:

- mobile: 320-767 CSS pixels;
- tablet: 768-1023 CSS pixels;
- desktop: 1024 CSS pixels and above.

Desktop keeps the persistent collapsible sidebar. Tablet uses an overlay drawer. Mobile uses a compact header plus modal navigation drawer; theme, workspace mode, Jobs, and Settings move into one menu. Drawers trap focus, close on Escape or route change, restore focus to the trigger, and prevent background scrolling.

The reader's course contents panel remains separate from the application navigation. On mobile it becomes its own drawer, while the reading column uses the full viewport width. Review, flashcard, and test controls stack without horizontal scrolling, and all interactive targets meet a 44-by-44 CSS-pixel minimum where the control is touch-primary.

### Acceptance criteria

- A query finds matching source text in a 181-section course without an LLM or network access.
- Search results navigate to the correct section and available source location.
- Re-ingest, lesson regeneration, note edits, and note deletion cannot leave stale search rows.
- Dashboard, reader, review, flashcards, tests, upload, Jobs, and Settings have no unintended horizontal scrolling at 320, 768, 1024, and 1440 CSS pixels.
- Keyboard and screen-reader behavior is preserved at every layout band.

## Program 5: import adapters and generalized source locations

### Normalized import boundary

Introduce a format-adapter interface that accepts a validated local asset and returns a normalized source document containing:

- detected metadata;
- ordered normalized sections;
- immutable extracted Markdown;
- stable source locators;
- extraction warnings and per-item failures;
- extractor name and version.

PDF becomes the first adapter without changing its extraction behavior. The ingest orchestration selects an adapter after content sniffing, not filename extension. All adapters preserve the current rules: zero LLM calls during ingest, content-addressed section identity, per-file failure isolation, versioned extraction, and lazy re-derivation of affected data.

### Source locators

Generalize page-only navigation to a structured locator:

- PDF: `page` with inclusive numeric range;
- PPTX: `slide` with inclusive numeric range;
- EPUB: `chapter` plus optional fragment;
- DOCX, Markdown, text, and HTML: `heading` plus optional ordinal.

Existing PDF `page_start` and `page_end` remain populated during the compatibility period. New locator fields are additive and become the navigation authority for non-PDF formats. Citation display strings remain opaque; structured locators travel beside them.

### Format sequence

The first expansion supports UTF-8 Markdown, plain text, and sanitized HTML using standard-library or already-installed parsing facilities. The second expansion supports DOCX, PPTX, and EPUB only after a dedicated dependency review covering maintenance, license, security, extraction fidelity, archive-bomb limits, and deterministic output.

Every format receives a fixture corpus including valid, malformed, oversized, non-English, image-heavy, and hostile inputs. Archive-based formats enforce compressed and expanded size limits, file-count limits, path traversal rejection, and content sniffing before parsing.

### Acceptance criteria

- PDF behavior and extraction snapshots remain unchanged after the adapter boundary is introduced.
- Markdown, text, and HTML assets produce readable sections and navigable locators without an LLM.
- A failed file does not block other files in the same course.
- Export preserves original assets, extracted Markdown, format provenance, and locators.
- DOCX, PPTX, and EPUB implementation does not begin until the dependency decision is recorded.

## Cross-cutting error handling

- API failures use stable machine-readable error codes plus safe human-readable detail.
- Frontend surfaces map known codes to recovery actions and use the shared `ErrorBanner` for transport/server failures.
- Retry is offered only when the failed operation is safe and the blocking condition has changed or may be transient.
- Async progress always includes a human-readable stage; stalled jobs link to Jobs.
- Derived-data rebuild failures never delete canonical source or learner data.

## Security and privacy

- The application remains bound to loopback by default.
- Secret-editing endpoints refuse non-loopback requests and enforce same-origin CSRF protection.
- Search excerpts are sanitized before rendering and never include raw HTML.
- HTML import uses an allowlist sanitizer before Markdown conversion or display.
- Archive formats receive traversal, decompression-size, and file-count defenses.
- Workspace mode is explicitly not authorization.
- No new external telemetry is introduced.

## Testing strategy

Each program begins with regression tests that capture current desired behavior and a failing test for each defect before implementation.

Required layers are:

- service tests for capability state, review counts, sample reconciliation, index lifecycle, and adapter normalization;
- router tests for typed errors, secret redaction, search bounds, source locators, and malformed uploads;
- migration tests for existing databases and downgrade behavior where supported;
- frontend component tests for setup recovery, Jobs retry gating, mode navigation, search interaction, drawer focus, and source navigation;
- viewport browser tests at 320, 768, 1024, and 1440 CSS pixels;
- end-to-end journeys for first run without AI, provider setup, upload/read/search, review with overdue and new cards, instructor-mode switching, and multi-format import;
- the existing full backend and frontend suites, typecheck, lint, build, and static architecture checks.

No test may call an external provider or network service. Provider checks, FTS capability variants, and format parsers use deterministic fixtures and stubs.

## Delivery and rollout

The programs ship in order. Each program has its own implementation plan and review gate. Database and API additions are additive before consumers switch, and compatibility fields remain until all frontend consumers and exports use the new contract.

1. Ship AI status, setup guidance, preflight blocking, and Jobs recovery.
2. Ship canonical review availability and explicit sample identity.
3. Ship workspace-mode navigation and route boundaries.
4. Ship search indexing/API, reader search, command palette, and responsive shell.
5. Ship the adapter boundary, then simple text formats, then dependency-reviewed archive formats.

Feature flags are used only where rollback requires them: credential editing, FTS-backed search, responsive navigation replacement, and each non-PDF adapter. Flags default off until migrations, targeted tests, and the full build gate pass. A flag may be removed only after the feature has run enabled-by-default through the targeted suite, full build gate, and complete manual end-to-end smoke without a rollback-triggering defect.

## Success measures

All measures are computed locally and shown only in diagnostic UI or logs:

- zero generation jobs created when the provider capability is unavailable;
- zero raw provider-configuration messages shown on learner surfaces;
- zero divergence between review summary and recommendation counts for the same learner, scope, and time;
- zero false sample hints for user-created courses;
- no instructor actions in default Learner navigation;
- successful deterministic search navigation in the large-course fixture;
- no horizontal overflow in the supported viewport matrix;
- unchanged PDF extraction snapshots after adapter introduction;
- full existing and new test gates pass before each program completes.

## Risks and mitigations

- **Credential UI increases local attack surface.** Restrict it to loopback, require same-origin CSRF protection, never return secrets, and allow disabling it entirely.
- **Review contract changes can alter scheduling UX.** Centralize counts first, add clock-controlled contract tests, then migrate consumers one at a time.
- **FTS index drift can hide content.** Treat the index as disposable derived data, update transactionally, and provide a deterministic rebuild.
- **Responsive work can regress keyboard behavior.** Reuse the existing focus-management patterns and make focus/escape/restore tests part of every drawer task.
- **Generalized locators touch citations and exports.** Add fields compatibly, preserve PDF page fields, and migrate navigation consumers before removing any legacy assumption.
- **Document parsers add supply-chain and hostile-input risk.** Gate archive formats behind a recorded dependency review and a hostile fixture corpus.

## Plan decomposition

This design produces five implementation plans:

1. `student-ai-readiness-and-jobs`
2. `student-correctness-review-and-sample`
3. `local-workspace-modes`
4. `local-search-and-responsive-shell`
5. `multi-format-import-adapters`

Each plan must follow test-first delivery, use existing utilities before new abstractions, add no dependency without explicit approval, and end with targeted verification plus the repository's full build gate.
