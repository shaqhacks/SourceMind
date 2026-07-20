#!/usr/bin/env bash
# Full gate: compile + backend tests + OpenAPI export + frontend typecheck/build.
# CI runs exactly this script — keep them in sync (brief: Testing law).
set -euo pipefail
cd "$(dirname "$0")"

# 'next build' and 'next dev' share frontend/.next; building while a dev server
# is live corrupts the dev cache (missing per-route build-manifest.json -> the
# reader route 500s with ENOENT). Abort early unless explicitly overridden.
# Local-dev guard only: a no-op in CI (nothing listens on :3000) and where lsof
# is unavailable — the 'if' condition also keeps a non-zero lsof from tripping
# 'set -e'.
if [ "${SMV2_ALLOW_BUILD_WITH_DEV:-}" != "1" ] && command -v lsof >/dev/null 2>&1 \
   && lsof -i:3000 -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "build.sh: a server is already listening on :3000 (a running ./dev.sh?)." >&2
  echo "  'next build' and 'next dev' share frontend/.next — building now can corrupt" >&2
  echo "  the dev cache. Stop ./dev.sh first, or set SMV2_ALLOW_BUILD_WITH_DEV=1 to override." >&2
  exit 1
fi

echo "== backend: sync deps =="
(cd backend && uv sync --quiet)

echo "== backend: compile =="
(cd backend && uv run python -m compileall -q app)

echo "== backend: tests =="
(cd backend && uv run pytest -q)

echo "== openapi: export =="
(cd backend && uv run python -m app.export_openapi ../openapi.json)

echo "== frontend: deps =="
if [ -f frontend/package-lock.json ] && [ "${CI:-}" = "true" ]; then
  (cd frontend && npm ci --no-audit --no-fund)
else
  (cd frontend && npm install --no-audit --no-fund)
fi

echo "== frontend: generate API client =="
(cd frontend && npm run gen:api)

echo "== frontend: typecheck =="
(cd frontend && npm run typecheck)

echo "== frontend: tests =="
(cd frontend && npm test -- --run)

echo "== frontend: build =="
(cd frontend && npm run build)

echo "BUILD OK"
