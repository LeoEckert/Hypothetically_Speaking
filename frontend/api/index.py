"""Vercel Python function entrypoint — wraps the FastAPI ASGI app as-is.

This file lives inside frontend/api/ (the Vercel project's Root Directory is
"frontend") so Vercel's build auto-detects it as a serverless function
alongside the static Vite build. The actual backend code isn't here in the
repo — the deploy workflow (.github/workflows/deploy-frontend.yml) stages a
copy of backend/ into frontend/api/backend/ (nested *under* this function's
own directory, not beside it — Vercel's Python builder bundles a function's
own directory tree, not sibling directories reached only via a runtime
sys.path append) right before `vercel deploy`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.server.app import app  # noqa: E402,F401
