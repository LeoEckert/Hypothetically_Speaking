from __future__ import annotations

import json
from pathlib import Path

VIEWER = Path(__file__).with_name("viewer.html")


def render_html(snapshot: dict, reload_url: str = "/snapshot.json") -> str:
    """`reload_url` is where the page re-fetches the snapshot: the sidecar
    server's /snapshot.json, or the API's /api/trajectory when embedded."""
    payload = json.dumps(snapshot, ensure_ascii=False)
    return (
        VIEWER.read_text(encoding="utf-8")
        .replace("__SNAPSHOT__", payload)
        .replace("__RELOAD_URL__", json.dumps(reload_url))
    )
