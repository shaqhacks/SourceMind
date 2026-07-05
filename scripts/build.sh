#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Single source of truth for backend dependencies
UV_DEPS=(--with-requirements "$ROOT_DIR/backend/requirements.txt")

run_step() {
  local label="$1"
  shift
  printf '\n==> %s\n' "$label"
  "$@"
}

run_step "Compile backend" uv run "${UV_DEPS[@]}" python -m compileall backend
run_step "Run backend tests" uv run "${UV_DEPS[@]}" pytest backend/tests
run_step "Build frontend" npm --prefix frontend run build

printf '\nBuild completed successfully.\n'
