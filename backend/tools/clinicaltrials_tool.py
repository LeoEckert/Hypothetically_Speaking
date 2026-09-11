"""ClinicalTrials.gov API v2: keyless trial-stage evidence for a target/compound."""
from __future__ import annotations

import httpx

API_URL = "https://clinicaltrials.gov/api/v2/studies"

SPEC = {
    "name": "clinicaltrials",
    "description": (
        "Search ClinicalTrials.gov for trials involving a compound, gene target, "
        "or intervention. Returns NCT id, title, and status for each hit — use to "
        "check whether a hypothesis is already in human trials."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "search term, e.g. a compound or intervention name"},
            "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    },
}

_MOCK_ITEMS = [
    {
        "id": "NCT:NCT00000000",
        "url": "https://clinicaltrials.gov/",
        "summary": "[MOCK - no network] Representative trial hit for query context.",
        "raw": {"mock": True},
    }
]


def run(args: dict) -> dict:
    query = args["query"]
    max_results = args.get("max_results", 5)
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                API_URL,
                params={"query.term": query, "pageSize": max_results, "format": "json"},
            )
            resp.raise_for_status()
            studies = resp.json().get("studies", [])
    except Exception as exc:
        return {
            "summary": f"ClinicalTrials.gov lookup failed ({exc}); returning mock placeholder.",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": str(exc),
        }

    if not studies:
        return {"summary": f"No trials found for '{query}'.", "items": [], "mock": False, "error": None}

    items = []
    for study in studies:
        proto = study.get("protocolSection", {})
        nct_id = proto.get("identificationModule", {}).get("nctId", "UNKNOWN")
        title = proto.get("identificationModule", {}).get("briefTitle", "")
        status = proto.get("statusModule", {}).get("overallStatus", "")
        phase = ", ".join(proto.get("designModule", {}).get("phases", []) or [])
        summary = f"{title} — status: {status}{f', phase: {phase}' if phase else ''}"
        items.append(
            {
                "id": f"NCT:{nct_id}",
                "url": f"https://clinicaltrials.gov/study/{nct_id}",
                "summary": summary,
                "raw": study,
            }
        )

    text_summary = "\n".join(f"[{it['id']}] {it['summary']}" for it in items)
    return {"summary": text_summary, "items": items, "mock": False, "error": None}
