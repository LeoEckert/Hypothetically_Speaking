"""g:Profiler: gene/pathway enrichment analysis — the required in-silico
experiment. Given a gene list, tests whether any biological pathway/GO term
is statistically over-represented. Keyless REST API.
"""
from __future__ import annotations

import httpx

API_URL = "https://biit.cs.ut.ee/gprofiler/api/gost/profile/"

SPEC = {
    "name": "run_enrichment",
    "description": (
        "Run a real gene/pathway enrichment analysis (g:Profiler g:GOSt) on a "
        "list of human gene symbols. Returns statistically over-represented GO "
        "terms/pathways with adjusted p-values. This is the in-silico "
        "experiment step — call it once you have a candidate gene list from "
        "extract_genes, and treat the result as computed evidence, not text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "genes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "human gene symbols, e.g. ['SIRT1', 'FOXO3', 'MTOR']",
            },
            "max_terms": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
        },
        "required": ["genes"],
    },
}

_MOCK_ITEMS = [
    {
        "id": "ENRICH:MOCK",
        "url": "https://biit.cs.ut.ee/gprofiler/gost",
        "summary": "[MOCK - no network] Representative enrichment result for query context.",
        "raw": {"mock": True},
    }
]


def run(args: dict) -> dict:
    genes = [g.strip() for g in args["genes"] if g.strip()]
    max_terms = args.get("max_terms", 8)
    if not genes:
        return {"summary": "No genes provided for enrichment analysis.", "items": [], "mock": False, "error": "empty_gene_list"}

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                API_URL,
                json={
                    "organism": "hsapiens",
                    "query": genes,
                    "sources": ["GO:BP", "KEGG", "REAC"],
                    "user_threshold": 0.05,
                    "significance_threshold_method": "g_SCS",
                    "no_evidences": True,
                },
            )
            resp.raise_for_status()
            result_rows = resp.json().get("result", [])
    except Exception as exc:
        return {
            "summary": f"g:Profiler enrichment failed ({exc}); returning mock placeholder.",
            "items": _MOCK_ITEMS,
            "mock": True,
            "error": str(exc),
        }

    if not result_rows:
        return {
            "summary": f"g:Profiler: no significantly enriched terms for gene set {genes}.",
            "items": [],
            "mock": False,
            "error": None,
        }

    result_rows.sort(key=lambda r: r.get("p_value", 1.0))
    items = []
    for row in result_rows[:max_terms]:
        term_id = row.get("native", row.get("term_id", "unknown"))
        cid = f"ENRICH:{term_id}"
        summary = (
            f"{row.get('name', term_id)} ({row.get('source', '')}) — "
            f"adj. p={row.get('p_value', float('nan')):.2e}, "
            f"{row.get('intersection_size', '?')}/{row.get('term_size', '?')} genes, "
            f"input genes: {genes}"
        )
        items.append(
            {
                "id": cid,
                "url": f"https://biit.cs.ut.ee/gprofiler/gost?query={'+'.join(genes)}",
                "summary": summary,
                "raw": row,
            }
        )

    text_summary = "\n".join(f"[{it['id']}] {it['summary']}" for it in items)
    return {"summary": text_summary, "items": items, "mock": False, "error": None}
