"""Tool registry: enable/disable filtering + uniform SPEC/run contract.

Every tool module under backend/tools/ exposes:
  SPEC: dict            -- Anthropic tool schema {name, description, input_schema}
  run(args: dict) -> dict -- executes the call, returns:
    {
      "summary": str,                # short text handed back to Claude as the tool_result
      "items": [                     # evidence entries to register for citation
        {"id": str, "url": str, "summary": str, "raw": dict}, ...
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
    "enrichment": enrichment_tool,
    "extract_genes": extract_genes_tool,
}


def enabled_tool_names() -> list[str]:
    raw = os.environ.get("ENABLED_TOOLS", ",".join(_ALL_TOOLS.keys()))
    names = [n.strip() for n in raw.split(",") if n.strip()]
    return [n for n in names if n in _ALL_TOOLS]


def get_specs() -> list[dict]:
    return [_ALL_TOOLS[name].SPEC for name in enabled_tool_names()]


def run_tool(name: str, args: dict) -> dict:
    if name not in enabled_tool_names():
        return {
            "summary": f"Tool '{name}' is disabled for this run (ENABLED_TOOLS).",
            "items": [],
            "mock": True,
            "error": "tool_disabled",
        }
    module = _ALL_TOOLS[name]
    try:
        return module.run(args)
    except Exception as exc:  # tool failures must not crash the agent loop
        return {
            "summary": f"Tool '{name}' raised an error: {exc}",
            "items": [],
            "mock": True,
            "error": str(exc),
        }
