#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

UV_DEPS=(
  --with pytest
  --with pydantic
  --with PyYAML
  --with fastapi
  --with httpx
  --with google-auth
  --with requests
  --with pypdf
  --with python-multipart
  --with python-frontmatter
  --with ollama
  --with sqlalchemy
  --with anthropic
  --with pymupdf
)

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
