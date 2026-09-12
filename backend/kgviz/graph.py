"""Read-only graph + deterministic depth-limited walk over the knowledge base."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque
from pathlib import Path

from backend.grounding.domain import concept_id, question_id
from backend.grounding.knowledge_base import DEFAULT_PATH

KIND_RANK = {"question": 0, "premise": 1, "hypothesis": 2, "concept": 3, "record": 4, "paper": 4}
EVIDENCE_KINDS = {"record", "paper"}
WALKS = ("bfs", "dfs")


def _open(path: Path | str) -> sqlite3.Connection:
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_graph(path: Path | str | sqlite3.Connection = DEFAULT_PATH) -> dict:
    """Nodes and edges as stored, plus virtual subject/object links.

    Those virtual edges are not written back — they only exist so a walk from
    the question reaches the concept chain the premises were checked against.
    """
    owns = not isinstance(path, sqlite3.Connection)
    connection = path if isinstance(path, sqlite3.Connection) else _open(path)
    connection.row_factory = sqlite3.Row
    nodes = []
    by_id: dict[str, dict] = {}
    for row in connection.execute(
        "SELECT id, kind, name, payload, first_seen, run_id FROM nodes ORDER BY id"
    ):
        payload = json.loads(row["payload"] or "{}")
        node = {
            "id": row["id"],
            "kind": row["kind"],
            "name": row["name"],
            "status": payload.get("status"),
            "label": payload.get("id") or row["name"],
            "subject": payload.get("subject"),
            "verb": payload.get("verb"),
            "object": payload.get("object"),
            "targets": payload.get("targets"),
            "absence_checked": payload.get("absence_checked"),
            "evidence_count": len(payload.get("evidence") or []),
            "intervention": payload.get("intervention"),
            "readout": payload.get("readout"),
            "model_system": payload.get("model_system"),
            "falsification": payload.get("falsification"),
            "supported_by": payload.get("supported_by") or [],
            "conflicts_with": payload.get("conflicts_with") or [],
            "dropped": payload.get("dropped"),
            "destination": payload.get("destination"),
            "run_id": row["run_id"],
            "first_seen": row["first_seen"],
        }
        nodes.append(node)
        by_id[node["id"]] = node

    edges = []
    seen: set[tuple[str, str, str]] = set()
    for row in connection.execute("SELECT src, dst, kind FROM edges ORDER BY src, dst, kind"):
        key = (row["src"], row["dst"], row["kind"])
        if key in seen:
            continue
        seen.add(key)
        edges.append({"src": row["src"], "dst": row["dst"], "kind": row["kind"], "virtual": False})

    for node in nodes:
        if node["kind"] != "premise":
            continue
        subject = node.get("subject")
        obj = node.get("object")
        if subject:
            sid = concept_id(subject)
            key = (node["id"], sid, "subject")
            if sid in by_id and key not in seen:
                seen.add(key)
                edges.append({"src": node["id"], "dst": sid, "kind": "subject", "virtual": True})
        if obj:
            oid = concept_id(obj)
            key = (node["id"], oid, "object")
            if oid in by_id and key not in seen:
                seen.add(key)
                edges.append({"src": node["id"], "dst": oid, "kind": "object", "virtual": True})

    for edge in list(edges):
        if edge["kind"] != "tests":
            continue
        key = (edge["dst"], edge["src"], "tested_by")
        if key in seen:
            continue
        seen.add(key)
        edges.append({"src": edge["dst"], "dst": edge["src"], "kind": "tested_by", "virtual": True})

    questions = [
        {"id": node["id"], "name": node["name"]} for node in nodes if node["kind"] == "question"
    ]
    # The reasoning log is the activation path itself: what was judged, in
    # what order, with the rationale — the viewer lists it stage by stage.
    steps = [
        dict(row)
        for row in connection.execute(
            "SELECT node_id, stage, verdict, rationale, run_id, at FROM steps ORDER BY id"
        )
    ]
    if owns:
        connection.close()
    return {"nodes": nodes, "edges": edges, "questions": questions, "steps": steps}


def resolve_seed(graph: dict, question: str | None = None) -> str:
    questions = graph["questions"]
    if not questions:
        raise ValueError("knowledge base has no question nodes yet")
    if question:
        wanted = question_id(question)
        if any(item["id"] == wanted for item in questions):
            return wanted
        raise ValueError(f"question not in knowledge base: {wanted}")
    return questions[0]["id"]


def _adjacency(graph: dict, include_records: bool) -> dict[str, list[tuple[str, str]]]:
    kinds = {node["id"]: node["kind"] for node in graph["nodes"]}
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in graph["edges"]:
        if not include_records and (
            kinds.get(edge["src"]) in EVIDENCE_KINDS or kinds.get(edge["dst"]) in EVIDENCE_KINDS
        ):
            continue
        adj[edge["src"]].append((edge["dst"], edge["kind"]))
    for src, neighbours in adj.items():
        neighbours.sort(key=lambda item: (KIND_RANK.get(kinds.get(item[0]), 9), item[0], item[1]))
        adj[src] = neighbours
    return adj


def walk(
    graph: dict,
    seed: str,
    mode: str = "bfs",
    depth: int = 3,
    include_records: bool = False,
) -> dict:
    """Depth-limited traversal. Neighbour order is sorted, so the visit list
    is identical for the same graph + seed + mode + depth."""
    if mode not in WALKS:
        raise ValueError(f"walk must be one of {WALKS}")
    if depth < 0:
        raise ValueError("depth must be >= 0")
    adj = _adjacency(graph, include_records)
    visited: list[dict] = []
    tree: list[dict] = []
    seen: set[str] = set()

    def visit(node_id: str, at: int) -> None:
        seen.add(node_id)
        visited.append({"id": node_id, "depth": at, "order": len(visited)})

    if mode == "bfs":
        queue = deque([(seed, 0)])
        seen.add(seed)
        while queue:
            node_id, at = queue.popleft()
            visited.append({"id": node_id, "depth": at, "order": len(visited)})
            if at >= depth:
                continue
            for neighbour, kind in adj.get(node_id, []):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                tree.append({"src": node_id, "dst": neighbour, "kind": kind})
                queue.append((neighbour, at + 1))
    else:
        def dfs(node_id: str, at: int) -> None:
            visit(node_id, at)
            if at >= depth:
                return
            for neighbour, kind in adj.get(node_id, []):
                if neighbour in seen:
                    continue
                tree.append({"src": node_id, "dst": neighbour, "kind": kind})
                dfs(neighbour, at + 1)

        dfs(seed, 0)

    return {
        "seed": seed,
        "walk": mode,
        "depth": depth,
        "include_records": include_records,
        "visited": visited,
        "tree_edges": tree,
    }


def snapshot(
    path: Path | str | sqlite3.Connection = DEFAULT_PATH,
    question: str | None = None,
    mode: str = "bfs",
    depth: int = 3,
    include_records: bool = False,
) -> dict:
    graph = load_graph(path)
    seed = resolve_seed(graph, question)
    activation = walk(graph, seed, mode=mode, depth=depth, include_records=include_records)
    return {**graph, **activation}
