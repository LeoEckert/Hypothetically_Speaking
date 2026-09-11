#!/usr/bin/env python3
"""Download GenAge (human) and DrugAge CSVs from the Human Ageing Genomic
Resources (HAGR) into backend/data/, for the genage_drugage tool to query
locally (HAGR does not expose a live query API).

Run once during setup: `python scripts/fetch_datasets.py`
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent.parent / "backend" / "data"

SOURCES = {
    "genage_human.csv": "https://genomics.senescence.info/genes/human_genes.zip",
    "drugage.csv": "https://genomics.senescence.info/drugs/dataset.zip",
}


def _fetch_and_extract_csv(url: str, dest_name: str) -> bool:
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                print(f"  no CSV found inside {url}", file=sys.stderr)
                return False
            data = zf.read(csv_names[0])
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / dest_name).write_bytes(data)
        print(f"  saved {dest_name} ({len(data)} bytes)")
        return True
    except Exception as exc:
        print(f"  failed to fetch {url}: {exc}", file=sys.stderr)
        return False


def main() -> None:
    print("Fetching HAGR GenAge/DrugAge datasets into backend/data/ ...")
    ok = True
    for dest_name, url in SOURCES.items():
        print(f"- {dest_name} <- {url}")
        ok &= _fetch_and_extract_csv(url, dest_name)

    if not ok:
        print(
            "\nOne or more downloads failed (network restrictions are common in "
            "sandboxed environments). The genage_drugage tool will run in mock "
            "mode until backend/data/genage_human.csv and backend/data/drugage.csv "
            "exist. You can also download them manually from "
            "https://genomics.senescence.info/download.html and place the CSVs "
            "there under those filenames.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
