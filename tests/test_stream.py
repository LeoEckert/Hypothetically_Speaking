"""Tests for GET /api/run/{run_id}/stream — the async rewrite that stopped
this endpoint from competing with every other route for Starlette's shared
(default 40-thread) sync thread pool. See backend/server/app.py: `_waiters`,
`_notify`, `stream_run`.

Note on TestClient: Starlette's TestClient runs the whole ASGI app call to
completion *inside* the blocking `client.stream(...)` call before returning
a response (it fully drains the body into an in-memory buffer — there is no
real incremental interleaving with the calling thread). So any test that
needs to publish events *while* a stream is open must do so from a separate
thread; publishing from the same thread that's blocked inside
`client.stream(...)` would deadlock (confirmed empirically while writing
these tests).

Imported at module scope (not inside a fixture), same reasoning as
tests/test_admin.py: avoids a lazy load_dotenv() side effect leaking real
provider keys into tests that run later in file order.
"""
import asyncio
import inspect
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.server import app as app_module  # noqa: E402
from backend.server.app import app as _app  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_module_state():
    app_module._run_events.clear()
    app_module._waiters.clear()
    app_module._results.clear()
    app_module._cancel_events.clear()
    yield
    app_module._run_events.clear()
    app_module._waiters.clear()
    app_module._results.clear()
    app_module._cancel_events.clear()


def _parse_sse(raw_lines: list[str]) -> list[dict | str]:
    out: list[dict | str] = []
    for line in raw_lines:
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: ") :]))
        elif line.strip() == ": keepalive":
            out.append("keepalive")
    return out


def test_replay_then_tail():
    """A connection replays what's already there, then tails new events
    published after it attached, and closes cleanly on stream_end."""
    client = TestClient(_app)
    app_module._run_events["r1"] = [{"type": "start", "run_id": "r1", "question": "q"}]
    app_module._waiters["r1"] = []

    def publisher():
        # Give event_gen a moment to register its waiter and drain the
        # initial replay before publishing more — not required for
        # correctness (the drain loop always re-checks length before
        # waiting) but keeps the two phases visibly distinct.
        time.sleep(0.1)
        app_module._run_events["r1"].append({"type": "phase", "phase": "plan"})
        app_module._notify("r1")
        app_module._run_events["r1"].append({"type": "stream_end"})
        app_module._notify("r1")

    threading.Thread(target=publisher, daemon=True).start()

    with client.stream("GET", "/api/run/r1/stream") as response:
        lines = [line for line in response.iter_lines() if line]

    events = _parse_sse(lines)
    assert events == [
        {"type": "start", "run_id": "r1", "question": "q"},
        {"type": "phase", "phase": "plan"},
        {"type": "stream_end"},
    ]


def test_two_concurrent_readers_both_get_every_event():
    """Two independent connections to the same run_id — the case a single
    shared Queue (wakes one consumer per put) would have gotten wrong."""
    app_module._run_events["r2"] = []
    app_module._waiters["r2"] = []

    results: dict[str, list] = {}

    def _reader(name: str):
        client = TestClient(_app)
        with client.stream("GET", "/api/run/r2/stream") as response:
            lines = [line for line in response.iter_lines() if line]
        results[name] = _parse_sse(lines)

    t1 = threading.Thread(target=_reader, args=("a",))
    t2 = threading.Thread(target=_reader, args=("b",))
    t1.start()
    t2.start()

    # Wait for both connections to actually attach before publishing, so
    # neither reader misses them by not having registered a waiter yet.
    deadline = time.monotonic() + 5.0
    while len(app_module._waiters.get("r2", [])) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(app_module._waiters["r2"]) == 2

    app_module._run_events["r2"].append({"type": "tool_call", "tool": "pubmed", "args": {}, "step": 1})
    app_module._notify("r2")
    app_module._run_events["r2"].append({"type": "stream_end"})
    app_module._notify("r2")

    t1.join(timeout=8)
    t2.join(timeout=8)

    expected = [{"type": "tool_call", "tool": "pubmed", "args": {}, "step": 1}, {"type": "stream_end"}]
    assert results["a"] == expected
    assert results["b"] == expected


def test_keepalive_on_silence(monkeypatch):
    monkeypatch.setattr(app_module, "KEEPALIVE_SECONDS", 0.2)
    client = TestClient(_app)
    app_module._run_events["r3"] = []
    app_module._waiters["r3"] = []

    def publisher():
        time.sleep(0.5)  # long enough for at least one 0.2s keepalive to fire first
        app_module._run_events["r3"].append({"type": "stream_end"})
        app_module._notify("r3")

    threading.Thread(target=publisher, daemon=True).start()

    with client.stream("GET", "/api/run/r3/stream") as response:
        lines = [line for line in response.iter_lines() if line]

    events = _parse_sse(lines)
    assert "keepalive" in events
    assert events[-1] == {"type": "stream_end"}


def test_stream_end_always_sent_even_if_worker_raises(monkeypatch):
    """The background worker's finally must always append stream_end, even
    when run_agent raises outside its own internal try/except."""

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "run_agent", _boom)
    client = TestClient(_app)

    resp = client.post("/api/run", json={"question": "does X help?"})
    run_id = resp.json()["run_id"]

    # The real POST /api/run background thread is independent of this
    # test's thread, so no deadlock risk here — it publishes stream_end on
    # its own once run_agent raises.
    with client.stream("GET", f"/api/run/{run_id}/stream") as response:
        lines = [line for line in response.iter_lines() if line]

    events = _parse_sse(lines)
    assert events[-1] == {"type": "stream_end"}
    assert run_id not in app_module._cancel_events


def test_no_stray_waiter_after_generator_close():
    """Closing the async generator early (what Starlette does on a client
    disconnect) must remove its waiter entry, not leak it forever."""
    app_module._run_events["r4"] = [{"type": "start"}]
    app_module._waiters["r4"] = []

    async def scenario():
        response = await app_module.stream_run("r4")
        gen = response.body_iterator
        first = await gen.__anext__()
        assert '"start"' in first
        assert len(app_module._waiters["r4"]) == 1
        await gen.aclose()

    asyncio.run(scenario())
    assert app_module._waiters["r4"] == []


def test_stream_run_is_truly_async():
    # Structural guard against an accidental revert to a plain `def` /
    # sync-generator implementation, which is exactly the regression this
    # whole file exists to catch — not a substitute for the behavioral
    # tests above.
    assert inspect.iscoroutinefunction(app_module.stream_run)
