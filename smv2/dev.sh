#!/usr/bin/env bash
# Run backend :8000 + frontend :3000 for local development.
set -euo pipefail
cd "$(dirname "$0")"

(cd backend && uv sync --quiet)
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install --no-audit --no-fund)
fi

(cd backend && uv run uvicorn app.main:app --reload --port "${SMV2_API_PORT:-8000}") &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT

(cd frontend && npm run dev)
