#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}}"
SOURCEMIND_CORS_ORIGINS="${SOURCEMIND_CORS_ORIGINS:-http://localhost:${FRONTEND_PORT},http://${FRONTEND_HOST}:${FRONTEND_PORT}}"

UV_DEPS=(
  --with pydantic
  --with PyYAML
  --with fastapi
  --with 'uvicorn[standard]'
  --with httpx
  --with google-auth
  --with requests
  --with pypdf
  --with python-multipart
  --with python-frontmatter
  --with ollama
)

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  wait "$BACKEND_PID" 2>/dev/null || true
  wait "$FRONTEND_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

printf 'Starting SourceMind...\n'
printf 'Backend:  http://%s:%s\n' "$BACKEND_HOST" "$BACKEND_PORT"
printf 'Frontend: http://%s:%s\n\n' "$FRONTEND_HOST" "$FRONTEND_PORT"

PYTHONPATH="$ROOT_DIR/..${PYTHONPATH:+:$PYTHONPATH}" \
  SOURCEMIND_CORS_ORIGINS="$SOURCEMIND_CORS_ORIGINS" \
  uv run "${UV_DEPS[@]}" \
  uvicorn SourceMind.backend.main:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  --reload &
BACKEND_PID="$!"

NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
  npm --prefix frontend run dev -- \
  --hostname "$FRONTEND_HOST" \
  --port "$FRONTEND_PORT" &
FRONTEND_PID="$!"

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  wait "$BACKEND_PID"
else
  wait "$FRONTEND_PID"
fi
