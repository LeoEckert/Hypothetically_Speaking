"""Amass: scientific memory across literature, trials, patents and biological data.

TODO (confirm at event): the exact REST/MCP contract for Amass is not yet
documented in this repo. This wrapper is written against a generic
"POST {AMASS_API_URL}/search {query}" shape with a bearer token, which is a
reasonable default for a retrieval API but MUST be checked against the real
docs/credentials handed out at the hackathon. Until then this tool safely
degrades to a mock response rather than guessing wrong and failing loudly.
"""
from __future__ import annotations

import os

import httpx

SPEC = {
    "name": "amass",
    "description": (
        "Query Amass's scientific memory layer across literature, clinical "
        "trials, patents, and biological data for a topic. Use this as a "
        "broad first pass to find what's already known before drilling into "
        "structured databases."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    },
}

_MOCK_ITEMS = [
    {
        "id": "AMASS:MOCK1",
        "url": "https://amass.ai/",
        "summary": "[MOCK - Amass API not configured/reachable] Representative memory-layer hit for query context.",
        "raw": {"mock": True},
    }
]


def run(args: dict) -> dict:
    api_key = os.environ.get("AMASS_API_KEY")
    base_url = os.environ.get("AMASS_API_URL", "").rstrip("/")
    if not api_key or not base_url:
        return {
            "summary": "Amass disabled: AMASS_API_KEY/AMASS_API_URL not set; returning mock placeholder.",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": "missing_config",
        }

    query = args["query"]
    max_results = args.get("max_results", 5)
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                f"{base_url}/search",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": query, "limit": max_results},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
    except Exception as exc:
        return {
            "summary": f"Amass lookup failed ({exc}); returning mock placeholder. "
            "(If this persists, check the AMASS_API_URL contract against current docs.)",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": str(exc),
        }

    items = []
    for i, r in enumerate(results, start=1):
        cid = f"AMASS:{r.get('id', i)}"
        summary = r.get("summary") or r.get("title") or str(r)[:200]
        items.append({"id": cid, "url": r.get("url", ""), "summary": summary, "raw": r})

    text_summary = "\n".join(f"[{it['id']}] {it['summary']}" for it in items)
    return {"summary": text_summary or f"No Amass results for '{query}'.", "items": items, "mock": False, "error": None}
