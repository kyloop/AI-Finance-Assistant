#!/usr/bin/env bash
# Start backend (:8000) and frontend (:5173) together. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$PWD/.venv/bin:$PATH"          # project Python + Node; no activation or conda needed

[ -x .venv/bin/node ] || { echo "Node not found in .venv (see README)"; exit 1; }
[ -d frontend/node_modules ] || (cd frontend && npm install)
[ -f finnie.db ] || python -m scripts.seed_db

uvicorn src.api.main:app --reload --port 8000 &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null; wait $BACKEND 2>/dev/null' EXIT INT TERM

cd frontend && npm run dev -- --port 5173 --strictPort
