"""Do the final hypotheses rest on the knowledge trajectory that was actually used?

    python -m scripts.check_trajectory backend/reports/demo_a.json[@runs/clean_1.db] [more...]

For each report: every final hypothesis must match a hypothesis node in the
knowledge base (`@path` after the report, else GROUNDING_KB or
runs/knowledge.db) whose `tests` edge leads to a premise the question's walk
visited. With several reports, also prints how
many hypothesis statements all runs share — the reproducibility number.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from backend.grounding.knowledge_base import DEFAULT_PATH
from backend.kgviz.graph import load_graph, resolve_seed, walk


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def check(argument: str) -> tuple[bool, set[str]]:
    report_path, _, kb_path = argument.partition("@")
    report = json.load(open(report_path))
    question = report.get("question") or ""
    graph = load_graph(kb_path or DEFAULT_PATH)
    seed = resolve_seed(graph, question)
    visited = {item["id"] for item in walk(graph, seed, depth=3)["visited"]}
    by_id = {node["id"]: node for node in graph["nodes"]}
    kb_hypotheses = {_norm(node["name"]): node for node in graph["nodes"] if node["kind"] == "hypothesis"}
    ok = True
    statements: set[str] = set()
    print(f"\n{Path(report_path).name} @ {kb_path or DEFAULT_PATH}: {question[:80]}")
    for hypothesis in report.get("hypotheses", []):
        statement = hypothesis["statement"].rstrip(".")
        statements.add(_norm(statement))
        node = kb_hypotheses.get(_norm(statement))
        if node is None:
            ok = False
            print(f"  FAIL not in knowledge base: {statement}")
            continue
        target = by_id.get(node["targets"])
        if target is None or target["id"] not in visited:
            ok = False
            print(f"  FAIL target premise not on the trajectory: {statement}")
            continue
        print(f"  ok   {hypothesis['id']} -> {target['name']} [{target['status']}]")
    return ok, statements


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    results = [check(path) for path in argv]
    passed = all(ok for ok, _ in results)
    if len(results) > 1:
        shared = set.intersection(*(s for _, s in results))
        union = set.union(*(s for _, s in results))
        print(f"\nshared across all {len(results)} runs: {len(shared)}/{len(union)} hypothesis statements")
        for statement in sorted(union - shared):
            print(f"  differs: {statement}")
    print("\nPASS" if passed else "\nFAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
