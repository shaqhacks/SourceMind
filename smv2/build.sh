#!/usr/bin/env bash
# Full gate: compile + backend tests + OpenAPI export + frontend typecheck/build.
# CI runs exactly this script — keep them in sync (brief: Testing law).
set -euo pipefail
cd "$(dirname "$0")"

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
