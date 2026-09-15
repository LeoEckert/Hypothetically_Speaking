"""Tests for POST /api/run: it runs the whole agent loop and streams its
trace as SSE within one request/response. There's no separate "start" +
"stream" endpoint any more and no server-side run cache to test against —
see backend/server/app.py's module docstring for why (this app has no state
that needs to survive between requests, which is what lets it run on
stateless/serverless hosting instead of a persistent VM).

Note on TestClient: Starlette's TestClient runs the whole ASGI app call to
completion *inside* the blocking `client.stream(...)` call before returning
a response (it fully drains the body into an in-memory buffer). That's fine
here because run_agent always executes on its own background thread (not the
test's thread) — same reasoning the old cross-request version of this file
documented.
"""
import asyncio
import inspect
import json
import sys
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.server import app as app_module  # noqa: E402
from backend.server.app import app as _app  # noqa: E402


def _parse_sse(raw_lines: list[str]) -> list[dict | str]:
    out: list[dict | str] = []
    for line in raw_lines:
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: ") :]))
        elif line.strip() == ": keepalive":
            out.append("keepalive")
    return out


def test_run_streams_events_and_ends_with_stream_end(monkeypatch):
    def _fake_run_agent(question, on_event=None, **kwargs):
        on_event({"type": "start", "run_id": "r1", "question": question})
        on_event({"type": "phase", "phase": "plan"})
        return {"report": "ok"}

    monkeypatch.setattr(app_module, "run_agent", _fake_run_agent)
    client = TestClient(_app)

    with client.stream("POST", "/api/run", json={"question": "does X help?"}) as response:
        lines = [line for line in response.iter_lines() if line]

    events = _parse_sse(lines)
    assert events[0]["type"] == "start"
    assert events[1] == {"type": "phase", "phase": "plan"}
    assert events[-1] == {"type": "stream_end"}


def test_stream_end_always_sent_even_if_worker_raises(monkeypatch):
    """The background worker's finally must always push stream_end, even
    when run_agent raises outside its own internal try/except."""

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "run_agent", _boom)
    client = TestClient(_app)

    with client.stream("POST", "/api/run", json={"question": "does X help?"}) as response:
        lines = [line for line in response.iter_lines() if line]

    events = _parse_sse(lines)
    assert events[-1] == {"type": "stream_end"}


def test_keepalive_on_silence(monkeypatch):
    monkeypatch.setattr(app_module, "KEEPALIVE_SECONDS", 0.2)

    def _slow_run_agent(question, on_event=None, **kwargs):
        time.sleep(0.5)  # long enough for at least one 0.2s keepalive to fire first
        on_event({"type": "done", "report": "ok"})
        return {"report": "ok"}

    monkeypatch.setattr(app_module, "run_agent", _slow_run_agent)
    client = TestClient(_app)

    with client.stream("POST", "/api/run", json={"question": "does X help?"}) as response:
        lines = [line for line in response.iter_lines() if line]

    events = _parse_sse(lines)
    assert "keepalive" in events
    assert events[-1] == {"type": "stream_end"}


def test_run_id_is_returned_in_a_response_header(monkeypatch):
    monkeypatch.setattr(app_module, "run_agent", lambda question, on_event=None, **kwargs: {"report": "ok"})
    client = TestClient(_app)

    with client.stream("POST", "/api/run", json={"question": "does X help?"}) as response:
        run_id = response.headers["X-Run-Id"]
        list(response.iter_lines())

    assert run_id and len(run_id) == 8


def test_watch_disconnect_sets_cancel_event(monkeypatch):
    """A closed connection is a run's cancel signal now — there's no
    separate /cancel endpoint or cross-request state to hold it in."""
    monkeypatch.setattr(app_module, "DISCONNECT_POLL_SECONDS", 0.01)

    class _FakeRequest:
        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 1  # still connected on the first poll, gone on the second

    async def scenario():
        request = _FakeRequest()
        cancel_event = threading.Event()
        await app_module._watch_disconnect(request, cancel_event)
        assert cancel_event.is_set()

    asyncio.run(scenario())


def test_start_run_is_async():
    # Structural guard: the endpoint must stay a coroutine so it can bridge
    # the background worker thread's events onto an asyncio.Queue natively
    # instead of blocking a shared sync thread-pool slot for a run's whole
    # lifetime — see backend/server/app.py's `start_run`.
    assert inspect.iscoroutinefunction(app_module.start_run)
