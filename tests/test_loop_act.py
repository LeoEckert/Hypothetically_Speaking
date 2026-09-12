"""Tests for the ACT-loop performance changes in backend/agent/loop.py:
prompt caching (cache_control shapes on system/tools/messages) and running
independent tool calls within one turn concurrently instead of sequentially.

Grounding is kept skipped throughout (no AMASS_API_KEY) so these tests never
touch the network — the Anthropic client itself is replaced with a fake that
returns canned responses, and backend.agent.loop.run_tool is monkeypatched
directly so no real tool wrappers run either.
"""
import copy
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from backend.agent import loop  # noqa: E402


def _usage(**overrides):
    base = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    base.update(overrides)
    return SimpleNamespace(**base)


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(name: str, tool_id: str, args: dict | None = None):
    return SimpleNamespace(type="tool_use", name=name, input=args or {}, id=tool_id)


def _message(content, stop_reason="end_turn", model="claude-sonnet-5", usage=None):
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model, usage=usage or _usage())


class _FakeStream:
    def __init__(self, final_message):
        self._final = final_message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        return iter([_text_of(self._final)])

    def get_final_message(self):
        return self._final


def _text_of(message) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", None) == "text")


class _FakeMessages:
    def __init__(self, create_responses, stream_responses):
        self._create = list(create_responses)
        self._stream = list(stream_responses)
        self.create_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    def create(self, **kwargs):
        # `messages`/`tools` are mutated in place by the loop after this call
        # returns (rolling cache markers, growing history) — snapshot deeply
        # so later inspection sees this call's payload as it was actually sent.
        self.create_calls.append(copy.deepcopy(kwargs))
        return self._create.pop(0)

    def stream(self, **kwargs):
        self.stream_calls.append(copy.deepcopy(kwargs))
        return _FakeStream(self._stream.pop(0))


def _install_fake_client(monkeypatch, create_responses, stream_responses):
    fake_messages = _FakeMessages(create_responses, stream_responses)
    fake_client = SimpleNamespace(messages=fake_messages)
    monkeypatch.setattr(loop, "Anthropic", lambda **kwargs: fake_client)
    return fake_messages


@pytest.fixture(autouse=True)
def _no_grounding(monkeypatch):
    monkeypatch.delenv("AMASS_API_KEY", raising=False)
    monkeypatch.setenv("ENABLED_TOOLS", "pubmed,tavily")


def _plain_run(monkeypatch, act_responses, run_tool):
    """PLAN + [act_responses...] + REVISE + REPORT, none carrying a
    hypotheses fence — the tests here care about caching/concurrency, not
    hypothesis parsing."""
    stream_responses = [
        _message([_text_block("plan done")]),  # PLAN
        _message([_text_block("revise done")]),  # REVISE
        _message([_text_block("report done")]),  # REPORT
    ]
    fake_messages = _install_fake_client(monkeypatch, act_responses, stream_responses)
    monkeypatch.setattr(loop, "run_tool", run_tool)
    return fake_messages


def _one_tool_call_then_stop():
    return [
        _message([_tool_use_block("pubmed", "t1")], stop_reason="tool_use"),
        _message([], stop_reason="end_turn"),
    ]


def _ok_run_tool(name, args, enabled_names=None):
    return {"summary": f"{name} ok", "items": [], "mock": False, "error": None}


def test_system_prompt_is_sent_as_a_cached_block_on_every_call(monkeypatch):
    fake_messages = _plain_run(monkeypatch, _one_tool_call_then_stop(), _ok_run_tool)

    loop.run_agent("does X affect ageing?")

    all_calls = fake_messages.create_calls + fake_messages.stream_calls
    assert len(all_calls) == 5  # PLAN (stream), 2x ACT (create), REVISE (stream), REPORT (stream)
    for call in all_calls:
        assert call["system"] == loop._SYSTEM_PROMPT_BLOCKS
        assert call["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_tool_specs_are_cached_on_the_last_entry(monkeypatch):
    fake_messages = _plain_run(monkeypatch, _one_tool_call_then_stop(), _ok_run_tool)

    loop.run_agent("does X affect ageing?")

    tools_sent = fake_messages.create_calls[0]["tools"]
    assert len(tools_sent) == 2  # ENABLED_TOOLS=pubmed,tavily
    assert "cache_control" not in tools_sent[0]
    assert tools_sent[-1]["cache_control"] == {"type": "ephemeral"}


def test_act_loop_rolls_a_cache_marker_across_turns(monkeypatch):
    act_responses = [
        _message([_tool_use_block("pubmed", "t1")], stop_reason="tool_use"),
        _message([_tool_use_block("tavily", "t2")], stop_reason="tool_use"),
        _message([], stop_reason="end_turn"),
    ]

    def run_tool(name, args, enabled_names=None):
        return {"summary": f"{name} ok", "items": [], "mock": False, "error": None}

    fake_messages = _plain_run(monkeypatch, act_responses, run_tool)
    loop.run_agent("does X affect ageing?")

    # 3 ACT turns were made; the 2nd and 3rd should each see exactly one
    # cache_control marker in their message history (the previous turn's
    # tool_results), never more than one at a time.
    def markers_in(messages):
        count = 0
        for m in messages:
            content = m["content"]
            if isinstance(content, list):
                count += sum(1 for block in content if isinstance(block, dict) and "cache_control" in block)
        return count

    assert len(fake_messages.create_calls) == 3
    assert markers_in(fake_messages.create_calls[0]["messages"]) == 0
    assert markers_in(fake_messages.create_calls[1]["messages"]) == 1
    assert markers_in(fake_messages.create_calls[2]["messages"]) == 1


def test_multiple_tool_calls_in_one_turn_run_concurrently(monkeypatch):
    delay = 0.25  # both calls take the same time: sequential ~0.5s, concurrent ~0.25s
    call_log: list[str] = []

    def run_tool(name, args, enabled_names=None):
        time.sleep(delay)
        call_log.append(name)
        return {
            "summary": f"{name} result",
            "items": [{"id": f"{name.upper()}:1", "url": "u", "summary": "s", "raw": {}}],
            "mock": False,
            "error": None,
        }

    act_responses = [
        _message([_tool_use_block("pubmed", "t1"), _tool_use_block("tavily", "t2")], stop_reason="tool_use"),
        _message([], stop_reason="end_turn"),
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

    def run_tool(name, args, enabled_names=None):
        call_log.append(name)
        return {"summary": f"{name} ok", "items": [], "mock": False, "error": None}

    act_responses = [
        _message([_tool_use_block("pubmed", "t1"), _tool_use_block("tavily", "t2")], stop_reason="tool_use"),
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
