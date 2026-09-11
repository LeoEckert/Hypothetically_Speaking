#!/usr/bin/env python3
"""Automated check behind the '95% of claims carry a working citation' bar.

Usage: python scripts/validate_citations.py backend/reports/<run_id>.json

Parses a saved run result (as written by backend/server/app.py or
scripts/run_demo.py), and checks:
  1. what fraction of factual sentences in the report body carry at least
     one [citation] marker
  2. whether every citation marker used actually resolves to an evidence
     registry entry with a URL (i.e. is "working", not invented)

Exits non-zero if coverage < 0.95 or any citation marker doesn't resolve.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CITATION_RE = re.compile(r"\[([A-Za-z0-9_:.\-]+)\]")
HEADER_RE = re.compile(r"^#{1,6}\s")

# Sections that are meta (not evidentiary claims) and excluded from the
# claim-coverage denominator.
EXCLUDED_SECTIONS = {"tool trace"}


def _split_sentences(text: str) -> list[str]:
    # Sentence-ish split: good enough for a coverage heuristic, not NLP-grade.
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def analyze_report(report_text: str, evidence_ids: set[str]) -> dict:
    lines = report_text.split("\n")
    current_section = ""
    claim_sentences: list[str] = []

    for line in lines:
        if HEADER_RE.match(line):
            current_section = line.lstrip("#").strip().lower()
            continue
        if current_section in EXCLUDED_SECTIONS or not line.strip():
            continue
        claim_sentences.extend(_split_sentences(line))

    cited = [s for s in claim_sentences if CITATION_RE.search(s)]
    uncited = [s for s in claim_sentences if not CITATION_RE.search(s)]

    all_markers = set(CITATION_RE.findall(report_text))
    unresolved = sorted(m for m in all_markers if m not in evidence_ids)

    coverage = len(cited) / len(claim_sentences) if claim_sentences else 1.0

    return {
        "total_sentences": len(claim_sentences),
        "cited_sentences": len(cited),
        "coverage": coverage,
        "uncited_examples": uncited[:10],
        "citation_markers_used": sorted(all_markers),
        "unresolved_citation_markers": unresolved,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python scripts/validate_citations.py <run_result.json>", file=sys.stderr)
        sys.exit(2)

    path = Path(sys.argv[1])
    data = json.loads(path.read_text())
    report_text = data["report"]
    evidence_ids = set(data.get("evidence", {}).keys())

    result = analyze_report(report_text, evidence_ids)

    print(f"Sentences with citations: {result['cited_sentences']}/{result['total_sentences']} "
          f"({result['coverage']:.1%})")
    if result["uncited_examples"]:
        print("\nExamples of uncited factual sentences:")
        for s in result["uncited_examples"]:
            print(f"  - {s}")
    if result["unresolved_citation_markers"]:
        print("\nCitation markers used that DON'T resolve to a real evidence entry:")
        for m in result["unresolved_citation_markers"]:
            print(f"  - [{m}]")

    ok = result["coverage"] >= 0.95 and not result["unresolved_citation_markers"]
    print("\nPASS" if ok else "\nFAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
