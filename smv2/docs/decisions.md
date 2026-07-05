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
