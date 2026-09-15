"""FastAPI app: POST /api/run runs the agent loop and streams its trace back
as Server-Sent Events within that single request/response — no separate
"start" + "stream" endpoints and no server-side run cache, so this app has
no state that needs to survive between requests (see the module docstring
note below on why that matters for where this can be deployed).

The frontend is a separately-deployed Vite/React app (see frontend/,
docs/DEPLOY.md) that talks to this API cross-origin — this app is a pure
JSON/SSE API.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

from backend.agent import admin  # noqa: E402

# Admin-rotated key overrides (backend/agent/admin.py) — loaded after the
# main .env with override=True so a rotation always wins, and survives a
# container rebuild even though the main .env can't be rewritten from inside
# the container (see admin.py's module docstring for why).
#
# NOTE: this, and the rest of backend/agent/admin.py's usage-history/key
# overrides, assume a persistent container filesystem. That's true on the
# Nebius VM this used to run on; it is not true of ephemeral/serverless
# hosting (e.g. Vercel Functions) — this subsystem needs a real persistent
# store (a small free-tier KV/Postgres) to keep working there. Left as a
# known gap rather than solved here. Neither ANTHROPIC_API_KEY nor
# OPENROUTER_API_KEY is platform-held by default any more (every user brings
# their own via the frontend's required onboarding popup) — an operator can
# still optionally set either here via the admin dashboard's key rotation
# (backend/agent/admin.py's ROTATABLE_KEYS) if they want a platform fallback.
load_dotenv(admin.ADMIN_OVERRIDES_PATH, override=True)

from backend.agent.evaluate import evaluate_hypothesis  # noqa: E402
from backend.agent.loop import HARD_MAX_TOOL_CALLS, _env_int, run_agent  # noqa: E402
from backend.agent.providers import get_provider  # noqa: E402
from backend.kgviz.graph import snapshot as trajectory_snapshot  # noqa: E402
from backend.kgviz.render import render_html as render_trajectory  # noqa: E402
from backend.tools import registry  # noqa: E402
from backend.tools.registry import all_specs, enabled_tool_names  # noqa: E402

app = FastAPI(title="Hypothetically Speaking — Longevity AI Scientist")

_default_origins = "http://localhost:5173,http://localhost:4173,http://127.0.0.1:5173,http://127.0.0.1:4173"
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]
for _loopback in ("http://127.0.0.1:5173", "http://127.0.0.1:4173"):
    if _loopback not in _allowed_origins:
        _allowed_origins.append(_loopback)
_allowed_origin_regex = os.environ.get("ALLOWED_ORIGIN_REGEX", r"https://.*\.vercel\.app$")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_allowed_origin_regex,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Admin-Token"],
    allow_credentials=False,
)

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
try:
    REPORTS_DIR.mkdir(exist_ok=True)
except OSError:
    pass  # read-only filesystem (serverless) — local-report-saving is a dev convenience only

# Mirrors scripts/run_demo.py's DEFAULT_QUESTION — the canonical demo question.
DEMO_QUESTION = (
    "Does activating SIRT1 plausibly extend human healthspan via improved "
    "mitochondrial biogenesis, and what is the strongest next experiment to "
    "test that mechanism?"
)
IS_DEV_MODE = os.environ.get("APP_ENV", "development") != "production"
DEFAULT_MAX_TOOL_CALLS = min(_env_int("MAX_TOOL_CALLS", 15), HARD_MAX_TOOL_CALLS)
KEEPALIVE_SECONDS = 15.0  # module constant so tests can shrink it
DISCONNECT_POLL_SECONDS = 1.0


class RunRequest(BaseModel):
    question: str
    max_tool_calls: int | None = None
    mode: str = "normal"  # "fast" — small/fast model everywhere, 4 grounding links, no second look — or "normal"
    # BYOK overrides, env-var-name -> value. ANTHROPIC_API_KEY or
    # OPENROUTER_API_KEY selects that LLM for this run — one of the two is
    # required in practice, since there's no platform-held LLM key (see
    # frontend's required onboarding popup). TAVILY_API_KEY/AMASS_API_KEY/
    # NEBIUS_API_KEY are optional per-request overrides of those tools' keys.
    # OPENROUTER_MODEL (not really a "key", but rides the same dict — see GET
    # /api/models) optionally pins a specific free model instead of
    # get_provider()'s live best-pick. Never persisted — used only to
    # construct clients/inject into tool args for this one request.
    api_keys: dict[str, str] = {}


class ToolToggleRequest(BaseModel):
    enabled: bool


class EvaluateRequest(BaseModel):
    comment: str = ""
    api_keys: dict[str, str] = {}
    # The finished run this evaluates (report/hypotheses/evidence) — the
    # client already received all of this in the `done` event at the end of
    # its streaming run; there is no server-side run cache to look it up
    # from any more (see the module docstring).
    run_result: dict


class KeyRotateRequest(BaseModel):
    value: str


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
        # Whether the *platform* holds a working key for each — independent
        # of whatever a given user has typed into Settings (BYOK). Anthropic
        # is expected to read false by default now: it's a user-supplied-only
        # upgrade, not something the platform funds.
        "anthropic_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openrouter_key_configured": bool(os.environ.get("OPENROUTER_API_KEY")),
        "default_provider": "openrouter",
    }


@app.get("/api/models")
def get_models():
    """Currently-available free, tool-calling-capable OpenRouter models
    (best first), plus which one get_provider() would pick by default right
    now — lets the frontend offer a model picker without ever hardcoding a
    model name itself. No key needed: OpenRouter's catalog is public."""
    from backend.agent.providers.openrouter_models import best_free_tool_model, list_free_tool_models

    return {"models": list_free_tool_models(), "recommended": best_free_tool_model()}


@app.get("/api/tools")
def get_tools():
    """The full tool roster (name + description from each tool's SPEC), with
    which ones are currently enabled via ENABLED_TOOLS, and whether each
    needs an API key at all (and whether the platform has one configured) —
    lets the frontend show BYOK hints without duplicating this mapping."""
    enabled = set(enabled_tool_names())
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "enabled": spec["name"] in enabled,
            "key_env_var": registry.KEY_ENV_VAR.get(spec["name"]),
            "key_configured": (
                bool(os.environ.get(registry.KEY_ENV_VAR[spec["name"]]))
                if spec["name"] in registry.KEY_ENV_VAR
                else True
            ),
            "paid": spec["name"] in registry.PAID_TOOLS,
        }
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


async def _watch_disconnect(request: Request, cancel_event: threading.Event) -> None:
    """A closed connection is this run's cancel signal — there's no separate
    /cancel endpoint or cross-request state to hold it in any more."""
    try:
        while True:
            if await request.is_disconnected():
                cancel_event.set()
                return
            await asyncio.sleep(DISCONNECT_POLL_SECONDS)
    except asyncio.CancelledError:
        raise


@app.post("/api/run")
async def start_run(req: RunRequest, request: Request):
    """Runs the whole agent loop and streams its trace as SSE within this one
    request — the loop runs in a background thread (run_agent is synchronous)
    while this coroutine drains its events off an asyncio.Queue and yields
    them, so the request's own connection lifetime is the run's lifetime.
    Closing the connection (browser cancel / tab close) is how a run is
    cancelled; there's nothing left to hold open across separate requests."""
    run_id = uuid.uuid4().hex[:8]
    requested = req.max_tool_calls if req.max_tool_calls is not None else DEFAULT_MAX_TOOL_CALLS
    effective_max_tool_calls = max(1, min(requested, HARD_MAX_TOOL_CALLS))

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    cancel_event = threading.Event()

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def _worker() -> None:
        try:
            result = run_agent(
                req.question,
                on_event=on_event,
                run_id=run_id,
                max_tool_calls=effective_max_tool_calls,
                should_cancel=cancel_event.is_set,
                mode="fast" if req.mode == "fast" else "normal",
                api_keys=req.api_keys,
            )
            try:
                (REPORTS_DIR / f"{run_id}.json").write_text(json.dumps(result, indent=2, default=str))
            except OSError:
                pass  # best-effort local-dev convenience; no-op on a read-only/ephemeral filesystem
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "stream_end"})

    threading.Thread(target=_worker, daemon=True).start()

    async def event_gen():
        watcher = asyncio.create_task(_watch_disconnect(request, cancel_event))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    # A long gap between events (slow tool calls, a
                    # multi-minute LLM response) over a real network hop
                    # could otherwise look like a dead connection.
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") == "stream_end":
                    return
        finally:
            watcher.cancel()

    return StreamingResponse(
        event_gen(), media_type="text/event-stream", headers={"X-Run-Id": run_id}
    )


@app.post("/api/run/{run_id}/evaluate")
def evaluate_run(run_id: str, req: EvaluateRequest):
    """Critique + revise the run's selected hypothesis via a fresh, one-off
    LLM judge+revise pass (see backend/agent/evaluate.py). `req.run_result`
    carries the finished run the client already has — there's no server-side
    run cache to look `run_id` up in any more."""
    try:
        provider = get_provider(req.api_keys, tier="main")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        return evaluate_hypothesis(req.run_result, req.comment, provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _trajectory(question: str | None, walk: str, depth: int, records: bool) -> dict:
    """Read-only view over runs/knowledge.db (GROUNDING_KB): the premises,
    verdicts and hypotheses a question activated, plus the reasoning log."""
    try:
        return trajectory_snapshot(question=question, mode=walk, depth=depth, include_records=records)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/trajectory")
def get_trajectory(question: str | None = None, walk: str = "bfs", depth: int = 3, records: bool = False):
    return _trajectory(question, walk, depth, records)


@app.get("/api/trajectory/view", response_class=HTMLResponse)
def view_trajectory(question: str | None = None, walk: str = "bfs", depth: int = 3, records: bool = False):
    """The knowledge-trajectory viewer as a page, for the frontend to embed."""
    from urllib.parse import urlencode

    query = urlencode({k: v for k, v in {"question": question, "walk": walk, "depth": depth, "records": int(records)}.items() if v is not None})
    return render_trajectory(_trajectory(question, walk, depth, records), reload_url=f"/api/trajectory?{query}")


@app.get("/api/admin/usage", dependencies=[Depends(admin.check_admin_token)])
def get_admin_usage():
    return admin.get_usage_snapshot()


@app.get("/api/admin/usage/history", dependencies=[Depends(admin.check_admin_token)])
def get_admin_usage_history(granularity: str = "day", days: int = 30, hours: int = 24):
    if granularity not in ("day", "hour"):
        raise HTTPException(status_code=400, detail="granularity must be 'day' or 'hour'")
    return admin.get_usage_history(granularity=granularity, days=days, hours=hours)


@app.get("/api/admin/keys", dependencies=[Depends(admin.check_admin_token)])
def get_admin_keys():
    return admin.list_keys()


@app.post("/api/admin/keys/{name}", dependencies=[Depends(admin.check_admin_token)])
def set_admin_key(name: str, req: KeyRotateRequest):
    return admin.set_key(name, req.value)


@app.post("/api/admin/token/rotate", dependencies=[Depends(admin.check_admin_token)])
def rotate_admin_token():
    return admin.rotate_admin_token()
