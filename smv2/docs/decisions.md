# SourceMind v2 — Decision Log (append-only)

Any reversal of a rule in `v2-build-brief.md` requires an ADR here explaining
what changed (brief: Process).

## ADR-001 — v2 lives in `smv2/` inside the SourceMind repo (2026-07-05)

Greenfield rebuild shares the repo with v1 rather than a new repository:
shared git history and issue context, one CI home, and v1 stays runnable
side-by-side during the rebuild. CI for v2 is a separate workflow
(`.github/workflows/smv2-ci.yml`) path-filtered to `smv2/**`.

## ADR-002 — uv + `pyproject.toml` is the single backend dependency source (2026-07-05)

v1 used `backend/requirements.txt`. v2 uses a uv-managed `pyproject.toml`
(+ lockfile) as the one source of truth: pinned, reproducible installs and one
command (`uv sync`) in dev and CI. The v1 rule's intent — exactly one place
declares dependencies, never `--with` lists in scripts — carries over intact.

## ADR-003 — Job worker is an in-process asyncio task over a durable Job table (2026-07-05)

The brief requires a Job table + worker loop, not a specific process topology.
Single-user laptop deployment favors one process. Durability comes from the
table + startup reconciler ("no status without a restart story"), not process
lifetime. Claims are atomic single-statement UPDATE…RETURNING with leases, so
a separate worker process remains a drop-in change if concurrency ever needs it.

## ADR-004 — `openapi.json` and generated TS types are committed artifacts (2026-07-05)

`build.sh` regenerates the OpenAPI schema and `frontend/lib/api/schema.d.ts`
on every run. Committing them makes API drift visible in diffs and lets the
frontend build without a running backend. The backend remains the source of
truth; hand-editing generated files is a bug.

## ADR-005 — Prompt delivery: instructions in system, source in tagged user content (2026-07-05)

Extracted PDF text is untrusted input interpolated into prompts. All
generation paths send instructions via the provider `system` parameter and
source material inside `<source_text>`/`<excerpts>` tags in the user message,
with the prompt instructing the model to treat tagged content strictly as
material. Structural mitigation, not a guarantee. Prompt files live in
`backend/prompts/vN/`; restructuring delivery without changing prompt text
does not bump the version.

## ADR-006 — Spend cap is a safety net with bounded overshoot, not billing enforcement (2026-07-05)

The per-course cap is checked immediately before each provider call and
re-checked after; overshoot is bounded by `llm_max_concurrency()` in-flight
calls. Hard atomicity over SQLite for an estimate-based cap was judged not
worth the locking complexity. The sequential worker makes the batch
(generate-all) case airtight, which is the realistic overspend scenario.

## ADR-007 — SM-2 bootstrap intervals extended to Hard/Easy (2026-07-05; corrected 2026-07-06 to match implementation)

Classic SM-2 only defines first-review intervals for Good. A card first
graded Hard or Easy would otherwise multiply interval 0 forever. As
implemented (`srs_service.py`): the first two non-Again reviews use fixed
baselines of 1d then 6d for Hard/Good/Easy alike; Easy applies its 1.3×
bonus on top of the baseline; the ease multiplier is skipped entirely until
reps ≥ 2 (ease is unproven early), and ease adjustments always take effect
the following review, not retroactively. Again: 10min due, reps reset,
lapse counted, ease −0.2 floored at 1.3. Full table in `test_srs_schedule`.
(Correction note: the original ADR text said "Easy 4d ease-adjusted" — that
never matched the code; this is a documentation fix, not a behavior change.)

## ADR-008 — Chat is synchronous; generation is jobs (2026-07-05)

Lesson/cards/quiz generation runs through the durable Job table (long,
restart-safe, SSE progress). Chat is a synchronous request/response: latency
budget is one completion, and fast-fail 429 from the limiter plus 504 on
provider timeout give the client honest, retryable signals. Chat turns
persist atomically only when the exchange succeeds — a failed reply leaves no
orphaned user turn.

## ADR-009 — SSRF guard built before any URL-fetch feature exists (2026-07-05)

`app/security/fetch.py` (scheme allowlist, resolve-then-check against
private/loopback/link-local/metadata ranges, size+timeout caps) is currently
uncalled by product code. It exists so the blessed path predates the feature,
and an architecture test confines httpx to `app/llm/` and `app/security/` so
any future URL fetch must go through it. Known limitation, documented in the
module: check-then-connect is not IP-pinned; tighten to a pinned transport
when a real caller lands.

## ADR-010 — Embeddings: Ollama-only, nullable, lazily backfilled (2026-07-05)

Anthropic has no embeddings API, so `AnthropicProvider.embed` raises
NotSupported and retrieval degrades to deterministic lexical ranking.
Embeddings backfill lazily (first chat triggers `embed_course`), per-chunk
failures stay NULL and are always skipped by the vector path. Chat therefore
works with zero embedding infrastructure, better with Ollama present.

## ADR-011 — Quiz generation input is course-scoped but bounded (2026-07-06)

Cross-section assessment is the feature's purpose: a quiz is meant to test
understanding across multiple chapters, not one section at a time like
lessons/cards. This deviates from the brief's "never a whole-book call"
letter — quiz generation can be handed the entire course's sections — but
input is capped at 24k combined characters via proportional per-section
heads regardless of book size, so every call remains bounded, single, and
never scales with book length. The letter (never whole-book) is deviated
from; the spirit (bounded cost, one call) is honored.

## ADR-012 — Generation streaming granularity is per-section (2026-07-06)

The brief's "stream section-by-section over SSE; the user reads finished
sections immediately" is implemented at section granularity: per-section
jobs flip that section readable one-by-one over SSE as each completes, and
within a single section's generation the UI shows staged progress (never a
bare spinner). Token-level streaming inside one section's own completion
call is explicitly out of scope. Chat citations are section-granular today
even though `Chunk.page` exists in the schema unused by navigation —
page-level citation jump is phase-2 polish, not a Phase 4 gap.
