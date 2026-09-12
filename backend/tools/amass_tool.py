"""Amass API: curated life-sciences data across Cores (literature, trials,
drugs, patents, genes, regulatory authorizations).

Contract confirmed 2026-09-12 against
https://api.amass.tech/api/doc/openapi.json:
  GET {AMASS_API_URL}/cores/{core}/records?query=...&limit=...
  Auth: Authorization: Bearer {AMASS_API_KEY}
  Response: {"data": [<core-specific record>, ...]}
"""
from __future__ import annotations

import os

import httpx

SPEC = {
    "name": "amass",
    "description": (
        "Query Amass's curated life-sciences data Cores: literature "
        "(biomedcore), clinical trials (trialcore), drugs/compounds "
        "(drugcore), patents (patentcore), genes (genecore), or drug "
        "regulatory authorizations (regulatorycore). Use this as a broad, "
        "curated first pass before drilling into other structured databases."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "core": {
                "type": "string",
                "enum": ["biomedcore", "trialcore", "drugcore", "patentcore", "genecore", "regulatorycore"],
                "default": "biomedcore",
                "description": "which Amass Core to search",
            },
            "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    },
}

_MOCK_ITEMS = [
    {
        "id": "AMASS:MOCK1",
        "url": "https://platform.amass.tech/",
        "summary": "[MOCK - Amass API not configured/reachable] Representative Core hit for query context.",
        "raw": {"mock": True},
    }
]


def _record_summary(core: str, rec: dict) -> tuple[str, str]:
    """Return (url, human-readable summary) for a record from the given Core."""
    if core == "biomedcore":
        title = rec.get("title") or "(untitled)"
        authors = ", ".join(rec.get("authors", [])[:3])
        journal = rec.get("journal") or ""
        pubdate = rec.get("publicationDate") or ""
        doi = rec.get("doi")
        pmid = rec.get("pmid")
        url = f"https://doi.org/{doi}" if doi else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "")
        return url, f"{title} — {authors} ({journal}, {pubdate})"
    if core == "trialcore":
        title = rec.get("briefTitle") or rec.get("officialTitle") or "(untitled trial)"
        status = rec.get("overallStatus") or ""
        phase = rec.get("phase") or ""
        url = rec.get("sourceUrl") or ""
        return url, f"{title} — status: {status}{f', phase: {phase}' if phase else ''}"
    if core == "patentcore":
        title = rec.get("title") or "(untitled patent)"
        pub_num = rec.get("publicationNumber") or ""
        assignees = ", ".join(rec.get("assignees", []) or [])[:200]
        return "", f"{title} ({pub_num}) — {assignees}"
    # drugcore / genecore / regulatorycore: field names not fully confirmed
    # yet against live docs — fall back to whatever name-like field exists.
    title = rec.get("name") or rec.get("title") or rec.get("preferredName") or str(rec)[:200]
    return "", str(title)


def get_credits() -> float | None:
    """GET {AMASS_API_URL}/credits/api-credits — returns the account's
    remaining credit balance (confirmed live response shape:
    {"data": {"remaining": <number>}}), or None if unconfigured, unreachable,
    or the response doesn't match that shape. Used for real (not guessed)
    per-run credit-consumption accounting (backend/agent/costs.py): call once
    before and once after a run's Amass calls and diff the two balances."""
    api_key = os.environ.get("AMASS_API_KEY")
    base_url = os.environ.get("AMASS_API_URL", "").rstrip("/")
    if not api_key or not base_url:
        return None
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{base_url}/credits/api-credits",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            return resp.json()["data"]["remaining"]
    except Exception:
        return None


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
    core = args.get("core", "biomedcore")
    max_results = args.get("max_results", 5)
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                f"{base_url}/cores/{core}/records",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"query": query, "limit": max_results},
            )
            resp.raise_for_status()
            records = resp.json().get("data", [])
    except Exception as exc:
        return {
            "summary": f"Amass lookup failed ({exc}); returning mock placeholder. "
            "(If this persists, check the AMASS_API_URL contract against current docs.)",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": str(exc),
        }

    items = []
    for rec in records:
        amass_id = rec.get("amassId", "unknown")
        url, summary = _record_summary(core, rec)
        items.append({"id": f"AMASS:{amass_id}", "url": url, "summary": summary, "raw": rec})

    text_summary = "\n".join(f"[{it['id']}] {it['summary']}" for it in items)
    return {
        "summary": text_summary or f"No Amass {core} results for '{query}'.",
        "items": items,
        "mock": False,
        "error": None,
    }
