"""Vercel Python function entrypoint — wraps the FastAPI ASGI app as-is.

This file lives inside frontend/ (the Vercel project's Root Directory) so
Vercel's build auto-detects it as a serverless function alongside the static
Vite build. The actual backend code isn't here in the repo — the deploy
workflow (.github/workflows/deploy-frontend.yml) stages a copy of backend/
and a trimmed requirements.txt into this directory's parent right before
`vercel deploy`, so this import resolves at build/runtime the same way it
does in the normal repo-root layout used everywhere else (local dev, tests,
scripts/run_demo.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.server.app import app  # noqa: E402,F401
