"""GenAge / DrugAge (Human Ageing Genomic Resources, HAGR): curated ageing-gene
and longevity-compound databases. No live API — datasets are downloaded once
via scripts/fetch_datasets.py into backend/data/ and queried locally here.
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GENAGE_CSV = DATA_DIR / "genage_human.csv"
DRUGAGE_CSV = DATA_DIR / "drugage.csv"

SPEC = {
    "name": "genage_drugage",
    "description": (
        "Search the curated GenAge (ageing-associated human genes) and DrugAge "
        "(compounds shown to affect lifespan in model organisms) databases from "
        "the Human Ageing Genomic Resources. Give a gene symbol or compound name."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "gene symbol or compound name"},
            "dataset": {
                "type": "string",
                "enum": ["genage", "drugage", "both"],
                "default": "both",
            },
            "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    },
}


def _search_csv(path: Path, query: str, source_label: str, max_results: int) -> list[dict]:
    if not path.exists():
        return []
    q = query.lower()
    items = []
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            haystack = " ".join(str(v) for v in row.values()).lower()
            if q in haystack:
                key_field = row.get("symbol") or row.get("compound_name") or row.get("name") or f"row{i}"
                summary_bits = [f"{k}={v}" for k, v in list(row.items())[:6] if v]
                items.append(
                    {
                        "id": f"HAGR:{source_label}:{key_field}:{i}",
                        "url": "https://genomics.senescence.info/",
                        "summary": f"[{source_label}] {'; '.join(summary_bits)}",
                        "raw": row,
                    }
                )
            if len(items) >= max_results:
                break
    return items


def run(args: dict) -> dict:
    query = args["query"]
    dataset = args.get("dataset", "both")
    max_results = args.get("max_results", 5)

    if not GENAGE_CSV.exists() and not DRUGAGE_CSV.exists():
        return {
            "summary": (
                "GenAge/DrugAge datasets not found locally. Run "
                "`python scripts/fetch_datasets.py` to download them from HAGR "
                "(https://genomics.senescence.info/download). Returning no results."
            ),
            "items": [],
            "mock": True,
            "error": "datasets_not_downloaded",
        }

    items: list[dict] = []
    if dataset in ("genage", "both"):
        items += _search_csv(GENAGE_CSV, query, "GenAge", max_results)
    if dataset in ("drugage", "both"):
        items += _search_csv(DRUGAGE_CSV, query, "DrugAge", max_results)
    items = items[:max_results]

    if not items:
        return {"summary": f"No GenAge/DrugAge matches for '{query}'.", "items": [], "mock": False, "error": None}

    text_summary = "\n".join(f"[{it['id']}] {it['summary']}" for it in items)
    return {"summary": text_summary, "items": items, "mock": False, "error": None}
