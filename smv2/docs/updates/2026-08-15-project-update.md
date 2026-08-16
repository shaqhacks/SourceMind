# SourceMind Project Update — 2026-08-15

## Current state

The student-experience remediation is merged into `main` at `7c0ec7c`. The release focuses on keeping local-first study workflows responsive, recoverable, and clear when Ollama or long-running generation jobs need attention.

## Delivered

- Added Ollama model discovery, installed-model selection, and actionable missing-model feedback.
- Streamed long-running generation progress with distinct queued, thinking, cancellation, retry, and background states.
- Made inline PDF pages the default reader experience.
- Unified flashcard review across course and chapter scopes with Again, Hard, Good, and Easy grading.
- Made chapter practice generation explicit per section, with a deliberate Generate all action.
- Prioritized chapter-test generation and atomically cancelled queued same-chapter practice jobs while preserving running and unrelated work.
- Added stateful desktop and mobile browser coverage for practice recovery, test priority, and generation streaming.

## Verification snapshot

- Backend: 902 tests passed.
- Frontend: 889 tests passed.
- Focused desktop and mobile end-to-end suite: 18 scenarios passed.
- OpenAPI drift check, TypeScript typecheck, and production build passed.

## New follow-up TODOs

### P2 — Make active test-job idempotency multi-process safe

The current same-scope `generate_test` reuse contract is correct for the documented single-process local runtime. Before adding multiple workers or remote deployment, enforce uniqueness with a database-backed constraint, advisory lock, or equivalent transactional claim.

### P3 — Refresh deprecated test and database adapters

The green backend suite still reports third-party deprecation warnings from the Starlette/httpx test client integration and Python 3.12 SQLite datetime adapters. Upgrade or replace these adapters before their compatibility paths are removed.

### P3 — Use native ARM64 Node on Apple Silicon

The production build succeeds, but local builds report that Node is running through Rosetta 2. Standardize the developer toolchain on native ARM64 Node to reduce build time and avoid architecture-specific package issues.

## Existing backlog

The maintained product and research backlog remains in [`TODOS.md`](../../TODOS.md). This update intentionally lists only follow-ups newly confirmed by the August remediation and verification work.
