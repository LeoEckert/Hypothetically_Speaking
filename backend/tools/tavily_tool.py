"""Tavily: live web retrieval over papers, trials and news."""
from __future__ import annotations

import os

import httpx

API_URL = "https://api.tavily.com/search"

SPEC = {
    "name": "tavily",
    "description": (
        "Live web search over papers, trials, and news. Use this for recent or "
        "broad-context information not well covered by the structured databases "
        "(PubMed, Open Targets, ClinicalTrials.gov, GenAge/DrugAge) — e.g. news "
        "coverage, preprints, or general background."
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
        "id": "S:MOCK1",
        "url": "https://example.org/mock-result",
        "title": "[MOCK] Representative web search hit",
        "summary": "[MOCK - no TAVILY_API_KEY] Representative web search hit for query context.",
        "raw": {"mock": True},
    }
]


def run(args: dict) -> dict:
    api_key = args.get("_user_api_key") or os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {
            "summary": "Tavily disabled: TAVILY_API_KEY not set; returning mock placeholder.",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": "missing_api_key",
        }

    query = args["query"]
    max_results = args.get("max_results", 5)
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                API_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                },
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
    except Exception as exc:
        return {
            "summary": f"Tavily search failed ({exc}); returning mock placeholder.",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": str(exc),
        }

    items = []
    for i, r in enumerate(results, start=1):
        cid = f"S:{abs(hash(r.get('url', str(i)))) % 100000}"
        title = r.get("title", "")
        summary = f"{title} — {r.get('content', '')[:200]}"
        items.append({"id": cid, "url": r.get("url", ""), "title": title, "summary": summary, "raw": r})

    text_summary = "\n".join(f"[{it['id']}] {it['summary']}" for it in items)
    return {"summary": text_summary or f"No Tavily results for '{query}'.", "items": items, "mock": False, "error": None}
