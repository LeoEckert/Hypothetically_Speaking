"""Knowledge-graph trajectory viewer — sidecar, does not touch the agent loop.

    python -m scripts.run_trajectory
    python -m scripts.run_trajectory --question "..." --walk bfs --depth 3
    python -m scripts.run_trajectory --open
    python -m scripts.run_trajectory --serve 8765

Reads runs/knowledge.db. --open writes runs/trajectory.html and launches it.
--serve re-reads the KB on each request so a second identical run lights the
same path.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.grounding.knowledge_base import DEFAULT_PATH
from backend.kgviz.graph import snapshot
from backend.kgviz.render import render_html

OUT = Path("runs/trajectory.html")


def _flags(argv: list[str]) -> tuple[dict[str, str | None], set[str]]:
    values: dict[str, str | None] = {}
    flags: set[str] = set()
    pending = None
    for argument in argv:
        if pending:
            values[pending] = argument
            pending = None
            continue
        if argument in {"--question", "--walk", "--depth", "--kb", "--serve"}:
            pending = argument
            continue
        if argument.startswith("--"):
            flags.add(argument)
            continue
        raise SystemExit(f"unknown argument: {argument}")
    if pending:
        raise SystemExit(f"{pending} needs a value")
    return values, flags


def _snapshot(values: dict[str, str | None], flags: set[str]) -> dict:
    depth = int(values.get("--depth") or 3)
    return snapshot(
        path=values.get("--kb") or DEFAULT_PATH,
        question=values.get("--question"),
        mode=values.get("--walk") or "bfs",
        depth=depth,
        include_records="--records" in flags,
    )


def _serve(port: int, values: dict[str, str | None], flags: set[str]) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            print(f"kgviz: {args[0]}", file=sys.stderr)

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            current = dict(values)
            current_flags = set(flags)
            if "question" in query:
                current["--question"] = query["question"][0]
            if "walk" in query:
                current["--walk"] = query["walk"][0]
            if "depth" in query:
                current["--depth"] = query["depth"][0]
            if query.get("records", [""])[0] in {"1", "true"}:
                current_flags.add("--records")
            body = snapshot_json = None
            if parsed.path in {"/", "/index.html"}:
                body = render_html(_snapshot(current, current_flags)).encode()
                ctype = "text/html; charset=utf-8"
            elif parsed.path == "/snapshot.json":
                snapshot_json = json.dumps(_snapshot(current, current_flags), ensure_ascii=False).encode()
                body = snapshot_json
                ctype = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"kgviz: http://127.0.0.1:{port}", file=sys.stderr)
    server.serve_forever()


def main(argv: list[str]) -> int:
    values, flags = _flags(argv)
    if "--help" in flags:
        print(__doc__)
        return 0
    if "--serve" in values:
        _serve(int(values["--serve"] or 8765), values, flags)
        return 0
    data = _snapshot(values, flags)
    html = render_html(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(html if "--html" in flags else json.dumps({
        "seed": data["seed"],
        "walk": data["walk"],
        "depth": data["depth"],
        "visited": data["visited"],
        "tree_edges": data["tree_edges"],
        "html": str(OUT),
    }, indent=2))
    if "--open" in flags:
        webbrowser.open(OUT.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
