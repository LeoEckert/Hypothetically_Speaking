"""Environment lookups that treat a blank value as unset.

`os.environ.get(name, default)` only applies `default` when the key is
missing entirely. On Vercel an env var declared in the dashboard with no
value still exists — it just reads as "" — and that empty string then
reaches whatever consumed it: `int("")` raised in the run budget,
`ENABLED_TOOLS=""` meant "no tools", and `ANTHROPIC_MODEL=""` was sent to
the API as the model name (400: "model: String should have at least 1
character"). Every env read that has a default belongs here.
"""

from __future__ import annotations

import os


def env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def env_int(name: str, default: int) -> int:
    raw = env_str(name)
    return int(raw) if raw else default
