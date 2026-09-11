"""FastAPI app: POST /api/run kicks off an agent run in a background thread;
GET /api/run/{run_id}/stream streams its trace as Server-Sent Events so the
frontend can show live progress. Also serves the minimal static frontend.
"""
from __future__ import annotations

import json
import queue
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from backend.agent.loop import run_agent  # noqa: E402

app = FastAPI(title="Hypothetically Speaking — Longevity AI Scientist")

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

_runs: dict[str, queue.Queue] = {}
_results: dict[str, dict] = {}


class RunRequest(BaseModel):
    question: str


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.post("/api/run")
def start_run(req: RunRequest):
    run_id = uuid.uuid4().hex[:8]
    q: queue.Queue = queue.Queue()
    _runs[run_id] = q

    def _worker():
        def on_event(event: dict) -> None:
            q.put(event)

        result = run_agent(req.question, on_event=on_event, run_id=run_id)
        _results[run_id] = result
        (REPORTS_DIR / f"{run_id}.json").write_text(json.dumps(result, indent=2, default=str))
        q.put({"type": "stream_end"})

    threading.Thread(target=_worker, daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/run/{run_id}/stream")
def stream_run(run_id: str):
    q = _runs.get(run_id)
    if q is None:
        return StreamingResponse(iter([]), media_type="text/event-stream")

    def event_gen():
        while True:
            event = q.get()
            yield f"data: {json.dumps(event, default=str)}\n\n"
            if event.get("type") == "stream_end":
                break

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/api/run/{run_id}/result")
def get_result(run_id: str):
    return _results.get(run_id, {"status": "not_ready"})
