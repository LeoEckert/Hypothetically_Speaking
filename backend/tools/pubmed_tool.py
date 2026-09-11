"""PubMed E-utilities: keyless structured literature search with verifiable PMIDs."""
from __future__ import annotations

import httpx

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

SPEC = {
    "name": "pubmed",
    "description": (
        "Search PubMed for peer-reviewed literature. Returns titles, authors, "
        "journal, year and a PMID citation for each hit. Prefer this over "
        "generic web search when you need a verifiable, structured citation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "PubMed search query"},
            "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    },
}

_MOCK_ITEMS = [
    {
        "id": "PMID:00000001",
        "url": "https://pubmed.ncbi.nlm.nih.gov/",
        "summary": "[MOCK - no network] Representative PubMed hit for query context.",
        "raw": {"mock": True},
    }
]


def run(args: dict) -> dict:
    query = args["query"]
    max_results = args.get("max_results", 5)
    try:
        with httpx.Client(timeout=15) as client:
            search_resp = client.get(
                ESEARCH,
                params={"db": "pubmed", "term": query, "retmode": "json", "retmax": max_results},
            )
            search_resp.raise_for_status()
            ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return {"summary": f"No PubMed results for '{query}'.", "items": [], "mock": False, "error": None}

            summary_resp = client.get(
                ESUMMARY, params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
            )
            summary_resp.raise_for_status()
            result = summary_resp.json().get("result", {})
    except Exception as exc:
        return {
            "summary": f"PubMed lookup failed ({exc}); returning mock placeholder.",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": str(exc),
        }

    items = []
    for pmid in ids:
        doc = result.get(pmid, {})
        title = doc.get("title", "").strip()
        journal = doc.get("fulljournalname", "")
        pubdate = doc.get("pubdate", "")
        authors = ", ".join(a.get("name", "") for a in doc.get("authors", [])[:3])
        summary = f"{title} — {authors} ({journal}, {pubdate})"
        items.append(
            {
                "id": f"PMID:{pmid}",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "summary": summary,
                "raw": doc,
            }
        )

    text_summary = "\n".join(f"[{it['id']}] {it['summary']}" for it in items)
    return {"summary": text_summary, "items": items, "mock": False, "error": None}
