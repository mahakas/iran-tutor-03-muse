#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run the offline DEMO profile (SQLite + synthetic data, no external APIs)
# as a two-process live stack:
#   * backend  : FastAPI / uvicorn   (default 0.0.0.0:8000)
#   * frontend : Next.js dev server  (default 0.0.0.0:3000)
#
# The browser only ever talks to the frontend; Next.js rewrites `/api/*`
# server-side to BACKEND_ORIGIN, so no localhost URL is baked into the client
# code and the app works behind a public preview/tunnel host.
#
# Usage:
#   ./scripts/run-live-demo.sh
#   FRONTEND_PORT=8080 BACKEND_PORT=9000 ./scripts/run-live-demo.sh
#
# Everything it creates (backend/.env, backend/.venv, node_modules,
# backend/demo.sqlite3, frontend/.next) is already git-ignored.
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

echo "==> repo: $ROOT"

# --- backend: env, venv, deps ---------------------------------------------
cd "$ROOT/backend"
if [ ! -f .env ]; then
  cp .env.demo.example .env
  echo "==> created backend/.env from .env.demo.example (demo mode, SQLite)"
fi

if [ ! -x .venv/bin/python ]; then
  echo "==> creating backend/.venv and installing requirements"
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt
fi

# --- frontend: deps --------------------------------------------------------
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  echo "==> installing frontend dependencies (npm ci)"
  npm ci --no-audit --no-fund
fi

# --- run both processes ----------------------------------------------------
pids=()
cleanup() {
  echo
  echo "==> stopping live demo"
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

cd "$ROOT/backend"
echo "==> backend  http://${BACKEND_HOST}:${BACKEND_PORT}  (docs at /docs)"
./.venv/bin/python -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
pids+=("$!")

cd "$ROOT/frontend"
echo "==> frontend http://${FRONTEND_HOST}:${FRONTEND_PORT}"
BACKEND_ORIGIN="http://127.0.0.1:${BACKEND_PORT}" \
  npx next dev --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT" &
pids+=("$!")

wait
