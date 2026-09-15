"""Tests for the ACT-loop behavior in backend/agent/loop.py: running
independent tool calls within one turn concurrently instead of sequentially,
and the budget cutoff applying mid-batch.

Provider-specific behavior (Anthropic's prompt-caching cache_control shapes)
is tested directly against AnthropicProvider in tests/test_anthropic_provider.py
instead — these tests exercise loop.py against a fake, provider-agnostic
LLMProvider so they don't need to know which one a run actually resolves to.

Grounding is kept skipped throughout (no AMASS_API_KEY) so these tests never
touch the network — backend.agent.loop.run_tool is monkeypatched directly so
no real tool wrappers run either.
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from backend.agent import loop  # noqa: E402
from backend.agent.providers.base import LLMResponse, ToolCall  # noqa: E402


def _usage(**overrides):
    base = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    base.update(overrides)
    return base


def _tool_call(name: str, tool_id: str, args: dict | None = None) -> ToolCall:
    return ToolCall(id=tool_id, name=name, input=args or {})


def _response(text: str = "", tool_calls=None, stop_reason: str = "end_turn") -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,
        usage=_usage(),
        model="claude-sonnet-5",
        raw={"role": "assistant", "content": text},
    )


class _FakeProvider:
    name = "anthropic"
    model = "claude-sonnet-5"
    key_source = "platform"

    def __init__(self, create_responses, stream_responses):
        self._create = list(create_responses)
        self._stream = list(stream_responses)
        self.create_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    def create(self, system, transcript, tools, max_tokens):
        self.create_calls.append({"system": system, "transcript": transcript, "tools": tools, "max_tokens": max_tokens})
        return self._create.pop(0)

    def stream(self, system, transcript, max_tokens, on_chunk):
        response = self._stream.pop(0)
        if response.text:
            on_chunk(response.text)
        self.stream_calls.append({"system": system, "transcript": transcript, "max_tokens": max_tokens})
        return response


def _install_fake_provider(monkeypatch, create_responses, stream_responses):
    fake_provider = _FakeProvider(create_responses, stream_responses)
    monkeypatch.setattr(loop, "get_provider", lambda *args, **kwargs: fake_provider)
    return fake_provider


@pytest.fixture(autouse=True)
def _no_grounding(monkeypatch):
    # Grounding no longer skips just because AMASS_API_KEY is unset (see
    # backend/agent/loop.py::_grounding_payload) — it falls back to keyless
    # PubMed/ClinicalTrials.gov sources instead, which would make these
    # ACT-loop-only tests hit the real network. They only care about
    # tool-call concurrency/budget, so grounding is stubbed out directly.
    monkeypatch.setattr(
        loop,
        "_grounding_payload",
        lambda *args, **kwargs: {
            "status": "skipped", "why": "grounding disabled for this test", "coherent": None,
            "triples": [], "destination": "", "premises": [], "knowledge_graph": "", "hypotheses": [], "rejected": [],
        },
    )
    monkeypatch.setenv("ENABLED_TOOLS", "pubmed,tavily")


def _plain_run(monkeypatch, act_responses, run_tool):
    """PLAN + [act_responses...] + REVISE + REPORT, none carrying a
    hypotheses fence — the tests here care about concurrency/budget, not
    hypothesis parsing."""
    stream_responses = [
        _response("plan done"),  # PLAN
        _response("revise done"),  # REVISE
        _response("report done"),  # REPORT
    ]
    fake_provider = _install_fake_provider(monkeypatch, act_responses, stream_responses)
    monkeypatch.setattr(loop, "run_tool", run_tool)
    return fake_provider


def test_multiple_tool_calls_in_one_turn_run_concurrently(monkeypatch):
    delay = 0.25  # both calls take the same time: sequential ~0.5s, concurrent ~0.25s
    call_log: list[str] = []

    def run_tool(name, args, enabled_names=None, api_keys=None):
        time.sleep(delay)
        call_log.append(name)
        return {
            "summary": f"{name} result",
            "items": [{"id": f"{name.upper()}:1", "url": "u", "summary": "s", "raw": {}}],
            "mock": False,
            "error": None,
        }

    act_responses = [
        _response(tool_calls=[_tool_call("pubmed", "t1"), _tool_call("tavily", "t2")], stop_reason="tool_use"),
        _response(stop_reason="end_turn"),
    ]
    _plain_run(monkeypatch, act_responses, run_tool)

    started = time.monotonic()
    result = loop.run_agent("does X affect ageing?")
    elapsed = time.monotonic() - started

    assert elapsed < delay * 1.6  # comfortably under the ~2x delay a sequential run would take
    assert set(call_log) == {"pubmed", "tavily"}
    assert set(result["evidence"].keys()) == {"PUBMED:1", "TAVILY:1"}
    # Original block order is preserved in the trace regardless of which
    # tool actually finished first (tavily/fast finishes well before pubmed).
    assert [t["tool_name"] for t in result["trace"]] == ["pubmed", "tavily"]


def test_budget_cutoff_applies_within_a_single_batch(monkeypatch):
    call_log: list[str] = []

    def run_tool(name, args, enabled_names=None, api_keys=None):
        call_log.append(name)
        return {"summary": f"{name} ok", "items": [], "mock": False, "error": None}

    act_responses = [
        _response(tool_calls=[_tool_call("pubmed", "t1"), _tool_call("tavily", "t2")], stop_reason="tool_use"),
    ]
    _plain_run(monkeypatch, act_responses, run_tool)

    events: list[dict] = []
    result = loop.run_agent("does X affect ageing?", max_tool_calls=1, on_event=events.append)

    # Only the first block in the batch actually ran; the second was skipped
    # for budget before it was even announced, matching the pre-existing
    # mid-batch cutoff behavior (tool_calls_made hits max_tool_calls after
    # the first call, so the second is never dispatched).
    assert call_log == ["pubmed"]
    assert len(result["trace"]) == 1
    assert result["trace"][0]["tool_name"] == "pubmed"
    assert result["partial"] is True

    tool_call_events = [e for e in events if e["type"] == "tool_call"]
    tool_result_events = [e for e in events if e["type"] == "tool_result"]
    assert [e["tool"] for e in tool_call_events] == ["pubmed"]
    assert [e["tool"] for e in tool_result_events] == ["pubmed"]
