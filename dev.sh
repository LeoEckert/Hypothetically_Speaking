#!/bin/bash
# Local dev mode: runs backend + frontend together, fully independent of any
# cloud deployment (Vercel/Nebius). Ctrl+C stops both.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "No .venv found — run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
if [ ! -f .env ]; then
  echo "No .env found — run: cp .env.example .env and fill in your API keys"
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend dependencies..."
  (cd frontend && npm install)
fi

trap 'kill 0' EXIT INT TERM

source .venv/bin/activate
uvicorn backend.server.app:app --reload &
(cd frontend && npm run dev) &

wait
