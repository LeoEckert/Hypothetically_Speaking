"""FastAPI app: POST /api/run kicks off an agent run in a background thread;
GET /api/run/{run_id}/stream streams its trace as Server-Sent Events. The
frontend is a separately-deployed Vite/React app (see frontend/, docs/DEPLOY.md)
that talks to this API cross-origin — this app is a pure JSON/SSE API.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

from backend.agent.loop import HARD_MAX_TOOL_CALLS, run_agent  # noqa: E402
from backend.tools import registry  # noqa: E402
from backend.tools.registry import all_specs, enabled_tool_names  # noqa: E402

app = FastAPI(title="Hypothetically Speaking — Longevity AI Scientist")

_default_origins = "http://localhost:5173,http://localhost:4173"
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]
_allowed_origin_regex = os.environ.get("ALLOWED_ORIGIN_REGEX", r"https://.*\.vercel\.app$")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_allowed_origin_regex,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# Mirrors scripts/run_demo.py's DEFAULT_QUESTION — the canonical demo question.
DEMO_QUESTION = (
    "Does activating SIRT1 plausibly extend human healthspan via improved "
    "mitochondrial biogenesis, and what is the strongest next experiment to "
    "test that mechanism?"
)
IS_DEV_MODE = os.environ.get("APP_ENV", "development") != "production"
DEFAULT_MAX_TOOL_CALLS = min(int(os.environ.get("MAX_TOOL_CALLS", 30)), HARD_MAX_TOOL_CALLS)

_run_events: dict[str, list[dict]] = {}
# Pure wake-up signals for stream_run — content is never read, just used to
# unblock a waiting reader when a new event lands in _run_events. The list is
# the single source of truth for event content, so readers never lose or
# double-deliver events regardless of when they attach.
_wakeups: dict[str, queue.Queue] = {}
_results: dict[str, dict] = {}
_cancel_events: dict[str, threading.Event] = {}


class RunRequest(BaseModel):
    question: str
    max_tool_calls: int | None = None


class ToolToggleRequest(BaseModel):
    enabled: bool


@app.get("/")
def index():
    return {"status": "ok", "service": "hypothetically-speaking-backend"}


@app.get("/api/config")
def get_config():
    return {
        "dev_mode": IS_DEV_MODE,
        "demo_question": DEMO_QUESTION if IS_DEV_MODE else "",
        "max_tool_calls_default": DEFAULT_MAX_TOOL_CALLS,
        "max_tool_calls_ceiling": HARD_MAX_TOOL_CALLS,
    }


@app.get("/api/tools")
def get_tools():
    """The full tool roster (name + description from each tool's SPEC), with
    which ones are currently enabled via ENABLED_TOOLS — lets the frontend
    show the user what the agent can call without duplicating the text."""
    enabled = set(enabled_tool_names())
    return [
        {"name": spec["name"], "description": spec["description"], "enabled": spec["name"] in enabled}
        for spec in all_specs()
    ]


@app.put("/api/tools/{name}")
def set_tool(name: str, req: ToolToggleRequest):
    """Runtime-only toggle, snapshotted into RunState.enabled_tools at the
    start of each run — an in-flight run is never affected, only the next one."""
    try:
        registry.set_tool_enabled(name, req.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
    enabled = set(enabled_tool_names())
    return {"name": name, "enabled": name in enabled}


@app.post("/api/run")
def start_run(req: RunRequest):
    run_id = uuid.uuid4().hex[:8]
    _run_events[run_id] = []
    _wakeups[run_id] = queue.Queue()
    cancel_event = threading.Event()
    _cancel_events[run_id] = cancel_event

    requested = req.max_tool_calls if req.max_tool_calls is not None else DEFAULT_MAX_TOOL_CALLS
    effective_max_tool_calls = max(1, min(requested, HARD_MAX_TOOL_CALLS))

    def _worker():
        def on_event(event: dict) -> None:
            _run_events[run_id].append(event)
            _wakeups[run_id].put(None)

        result = run_agent(
            req.question,
            on_event=on_event,
            run_id=run_id,
            max_tool_calls=effective_max_tool_calls,
            should_cancel=cancel_event.is_set,
        )
        _results[run_id] = result
        (REPORTS_DIR / f"{run_id}.json").write_text(json.dumps(result, indent=2, default=str))
        _run_events[run_id].append({"type": "stream_end"})
        _wakeups[run_id].put(None)
        _cancel_events.pop(run_id, None)

    threading.Thread(target=_worker, daemon=True).start()
    return {"run_id": run_id, "max_tool_calls": effective_max_tool_calls}


@app.post("/api/run/{run_id}/cancel")
def cancel_run(run_id: str):
    event = _cancel_events.get(run_id)
    if event is None:
        raise HTTPException(status_code=404, detail="run not found or already finished")
    event.set()
    return {"run_id": run_id, "cancelling": True}


@app.get("/api/run/{run_id}/stream")
def stream_run(run_id: str):
    if run_id not in _run_events:
        return StreamingResponse(iter([]), media_type="text/event-stream")

    def event_gen():
        # _run_events is the single source of truth; each connection tracks
        # its own read position into it, so a reload or a late "View live
        # run" attach replays everything so far exactly once, and a live
        # tail never double-delivers what replay already showed.
        next_index = 0
        while True:
            events = _run_events[run_id]
            while next_index < len(events):
                event = events[next_index]
                next_index += 1
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") == "stream_end":
                    return

            # Nothing new yet — wait for a wake-up. A long gap between
            # events (slow tool calls, a multi-minute Anthropic response)
            # over a real network hop could otherwise look like a dead
            # connection to an intermediary; send an SSE comment line as a
            # keepalive instead of blocking forever.
            try:
                _wakeups[run_id].get(timeout=15)
            except queue.Empty:
                yield ": keepalive\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/api/run/{run_id}/result")
def get_result(run_id: str):
    return _results.get(run_id, {"status": "not_ready"})
