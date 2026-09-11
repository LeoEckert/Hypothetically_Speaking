"""Open Targets Platform GraphQL API: keyless target-disease association evidence."""
from __future__ import annotations

import httpx

GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"

SPEC = {
    "name": "open_targets",
    "description": (
        "Look up genetic/genomic evidence linking a gene target to diseases via "
        "the Open Targets Platform. Give a gene symbol (e.g. 'SIRT1', 'APOE'); "
        "returns the diseases most strongly associated with that target and an "
        "association score, backed by integrated genetic/functional evidence."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "target_symbol": {"type": "string", "description": "gene symbol, e.g. SIRT1"},
            "max_diseases": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        },
        "required": ["target_symbol"],
    },
}

_SEARCH_QUERY = """
query Search($q: String!) {
  search(queryString: $q, entityNames: ["target"]) {
    hits { id name entity }
  }
}
"""

_ASSOC_QUERY = """
query TargetAssoc($ensemblId: String!, $size: Int!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    associatedDiseases(page: {index: 0, size: $size}) {
      rows {
        disease { id name }
        score
      }
    }
  }
}
"""

_MOCK_ITEMS = [
    {
        "id": "OT:MOCK",
        "url": "https://platform.opentargets.org/",
        "summary": "[MOCK - no network] Representative target-disease association for query context.",
        "raw": {"mock": True},
    }
]


def run(args: dict) -> dict:
    symbol = args["target_symbol"]
    max_diseases = args.get("max_diseases", 5)
    try:
        with httpx.Client(timeout=15) as client:
            search_resp = client.post(
                GRAPHQL_URL, json={"query": _SEARCH_QUERY, "variables": {"q": symbol}}
            )
            search_resp.raise_for_status()
            hits = search_resp.json()["data"]["search"]["hits"]
            target_hit = next((h for h in hits if h["entity"] == "target"), None)
            if target_hit is None:
                return {
                    "summary": f"Open Targets: no target found matching '{symbol}'.",
                    "items": [],
                    "mock": False,
                    "error": None,
                }
            ensembl_id = target_hit["id"]

            assoc_resp = client.post(
                GRAPHQL_URL,
                json={
                    "query": _ASSOC_QUERY,
                    "variables": {"ensemblId": ensembl_id, "size": max_diseases},
                },
            )
            assoc_resp.raise_for_status()
            target_data = assoc_resp.json()["data"]["target"]
    except Exception as exc:
        return {
            "summary": f"Open Targets lookup failed ({exc}); returning mock placeholder.",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": str(exc),
        }

    approved_symbol = target_data.get("approvedSymbol", symbol)
    rows = target_data.get("associatedDiseases", {}).get("rows", [])
    if not rows:
        return {
            "summary": f"Open Targets: '{approved_symbol}' ({ensembl_id}) has no scored disease associations.",
            "items": [],
            "mock": False,
            "error": None,
        }

    items = []
    for row in rows:
        disease = row["disease"]
        score = row["score"]
        cid = f"OT:{ensembl_id}:{disease['id']}"
        summary = f"{approved_symbol} ({ensembl_id}) — {disease['name']} association score {score:.3f}"
        items.append(
            {
                "id": cid,
                "url": f"https://platform.opentargets.org/evidence/{ensembl_id}/{disease['id']}",
                "summary": summary,
                "raw": row,
            }
        )

    text_summary = "\n".join(f"[{it['id']}] {it['summary']}" for it in items)
    return {"summary": text_summary, "items": items, "mock": False, "error": None}
