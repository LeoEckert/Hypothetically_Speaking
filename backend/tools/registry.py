"""Tool registry: enable/disable filtering + uniform SPEC/run contract.

Every tool module under backend/tools/ exposes:
  SPEC: dict            -- Anthropic tool schema {name, description, input_schema}
  run(args: dict) -> dict -- executes the call, returns:
    {
      "summary": str,                # short text handed back to Claude as the tool_result
      "items": [                     # evidence entries to register for citation
        {"id": str, "url": str, "title": str, "summary": str, "raw": dict}, ...
      ],
      "mock": bool,                  # True if this was a fallback/offline response
      "error": str | None,           # set if something went wrong (still non-fatal)
    }
"""
from __future__ import annotations

import os

from backend.tools import (
    amass_tool,
    clinicaltrials_tool,
    enrichment_tool,
    extract_genes_tool,
    genage_drugage_tool,
    open_targets_tool,
    pubmed_tool,
    tavily_tool,
)

_ALL_TOOLS = {
    "tavily": tavily_tool,
    "amass": amass_tool,
    "open_targets": open_targets_tool,
    "pubmed": pubmed_tool,
    "clinicaltrials": clinicaltrials_tool,
    "genage_drugage": genage_drugage_tool,
    "run_enrichment": enrichment_tool,
    "extract_genes": extract_genes_tool,
}

# Which env var a tool's key comes from, for tools that need one at all — used
# both to inject a per-request user-supplied override (run_tool below) and to
# tell the frontend which tools are BYOK-able (GET /api/tools).
KEY_ENV_VAR = {
    "tavily": "TAVILY_API_KEY",
    "amass": "AMASS_API_KEY",
    "extract_genes": "NEBIUS_API_KEY",
}


# Runtime, in-memory overrides layered on top of the ENABLED_TOOLS env var —
# set via PUT /api/tools/{name} (backend/server/app.py). Intentionally not
# persisted: a fresh process always starts from ENABLED_TOOLS again.
_runtime_override: dict[str, bool] = {}


def _env_enabled_set() -> set[str]:
    raw = os.environ.get("ENABLED_TOOLS", ",".join(_ALL_TOOLS.keys()))
    names = {n.strip() for n in raw.split(",") if n.strip()}
    return {n for n in names if n in _ALL_TOOLS}


def enabled_tool_names() -> list[str]:
    enabled = _env_enabled_set()
    for name, on in _runtime_override.items():
        if on:
            enabled.add(name)
        else:
            enabled.discard(name)
    return [n for n in _ALL_TOOLS if n in enabled]


def set_tool_enabled(name: str, enabled: bool) -> None:
    if name not in _ALL_TOOLS:
        raise KeyError(name)
    _runtime_override[name] = enabled


def get_specs() -> list[dict]:
    return [_ALL_TOOLS[name].SPEC for name in enabled_tool_names()]


def all_specs() -> list[dict]:
    """Every registered tool's SPEC, regardless of ENABLED_TOOLS — used by the
    frontend to show the user the full tool roster (with enabled/disabled state)."""
    return [_ALL_TOOLS[name].SPEC for name in _ALL_TOOLS]


def run_tool(
    name: str, args: dict, enabled_names: set[str] | None = None, api_keys: dict[str, str] | None = None
) -> dict:
    """`enabled_names`, when given, is used instead of re-checking the live
    registry state — this is how a run snapshots which tools it's allowed to
    call at start time, so a mid-run toggle never changes that run's behavior
    or cost accounting (backend/agent/loop.py).

    `api_keys` (env-var-name -> value, e.g. from RunRequest.api_keys) is a
    per-request, user-supplied override for a tool's key. It's injected into
    a reserved `_user_api_key` args field rather than changing this
    function's or `run(args: dict)`'s signature — each tool's own
    `os.environ.get(...)` call site checks that field first."""
    allowed = enabled_names if enabled_names is not None else set(enabled_tool_names())
    if name not in allowed:
        return {
            "summary": f"Tool '{name}' is disabled for this run (ENABLED_TOOLS).",
            "items": [],
            "mock": True,
            "error": "tool_disabled",
        }
    module = _ALL_TOOLS[name]
    env_var = KEY_ENV_VAR.get(name)
    call_args = args
    if env_var and api_keys and api_keys.get(env_var):
        call_args = {**args, "_user_api_key": api_keys[env_var]}
    try:
        return module.run(call_args)
    except Exception as exc:  # tool failures must not crash the agent loop
        return {
            "summary": f"Tool '{name}' raised an error: {exc}",
            "items": [],
            "mock": True,
            "error": str(exc),
        }
