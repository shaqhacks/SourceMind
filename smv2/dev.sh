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

# `./build.sh` runs `next build`, which writes a production .next (BUILD_ID,
# prerender-manifest, server/, ...). A subsequent `next dev` reading that
# production build serves 404 on every route. `next dev` never creates a
# BUILD_ID, so its presence means a leftover production build is here — clear
# it so dev starts from a clean cache. Only triggers right after a build;
# repeated `./dev.sh` runs (no build in between) have no BUILD_ID and skip it.
if [ -f frontend/.next/BUILD_ID ]; then
  echo "dev.sh: clearing a leftover production build in frontend/.next"
  rm -rf frontend/.next
fi

(cd frontend && npm run dev)
