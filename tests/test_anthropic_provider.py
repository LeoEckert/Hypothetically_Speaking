"""Tests for AnthropicProvider: prompt-caching shapes (cache_control on the
system block, the last tool spec, and a rolling marker on tool-result turns).

Migrated out of test_loop_act.py now that backend/agent/loop.py is
provider-agnostic — these are Anthropic-specific wire-format details that
belong at this layer, not exercised through the whole agent loop.
"""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from backend.agent.providers.base import Transcript, ToolResult  # noqa: E402


def _usage():
    return SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0)


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(name, tool_id, args=None):
    return SimpleNamespace(type="tool_use", name=name, input=args or {}, id=tool_id)


def _message(content, stop_reason="end_turn", model="claude-sonnet-5"):
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model, usage=_usage())


def _text_of(message) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", None) == "text")


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


class _FakeMessages:
    def __init__(self, create_responses=None, stream_responses=None):
        self._create = list(create_responses or [])
        self._stream = list(stream_responses or [])
        self.create_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    def create(self, **kwargs):
        self.create_calls.append(copy.deepcopy(kwargs))
        return self._create.pop(0)

    def stream(self, **kwargs):
        self.stream_calls.append(copy.deepcopy(kwargs))
        return _FakeStream(self._stream.pop(0))


def _provider_with(create_responses=None, stream_responses=None) -> AnthropicProvider:
    provider = AnthropicProvider(api_key="test", model="claude-sonnet-5")
    provider.client = SimpleNamespace(messages=_FakeMessages(create_responses, stream_responses))
    return provider


def test_system_prompt_is_sent_as_a_cached_block():
    provider = _provider_with(stream_responses=[_message([_text_block("plan done")])])
    transcript = Transcript()
    transcript.add_user_text("hello")

    provider.stream(system="SYS", transcript=transcript, max_tokens=100, on_chunk=lambda c: None)

    call = provider.client.messages.stream_calls[0]
    assert call["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]


def test_tool_specs_are_cached_on_the_last_entry():
    provider = _provider_with(create_responses=[_message([], stop_reason="end_turn")])
    transcript = Transcript()
    transcript.add_user_text("hello")
    tools = [
        {"name": "a", "description": "d", "input_schema": {}},
        {"name": "b", "description": "d", "input_schema": {}},
    ]

    provider.create(system="SYS", transcript=transcript, tools=tools, max_tokens=100)

    tools_sent = provider.client.messages.create_calls[0]["tools"]
    assert len(tools_sent) == 2
    assert "cache_control" not in tools_sent[0]
    assert tools_sent[-1]["cache_control"] == {"type": "ephemeral"}


def test_tool_results_turns_roll_a_single_cache_marker():
    provider = _provider_with(
        create_responses=[
            _message([_tool_use_block("pubmed", "t1")], stop_reason="tool_use"),
            _message([_tool_use_block("tavily", "t2")], stop_reason="tool_use"),
            _message([], stop_reason="end_turn"),
        ]
    )
    transcript = Transcript()
    transcript.add_user_text("hello")

    def markers_in(messages):
        count = 0
        for m in messages:
            content = m["content"]
            if isinstance(content, list):
                count += sum(1 for block in content if isinstance(block, dict) and "cache_control" in block)
        return count

    r1 = provider.create(system="SYS", transcript=transcript, tools=[], max_tokens=100)
    transcript.add_assistant(r1)
    transcript.add_tool_results([ToolResult(tool_call_id="t1", content="result1")])

    r2 = provider.create(system="SYS", transcript=transcript, tools=[], max_tokens=100)
    transcript.add_assistant(r2)
    transcript.add_tool_results([ToolResult(tool_call_id="t2", content="result2")])

    provider.create(system="SYS", transcript=transcript, tools=[], max_tokens=100)

    calls = provider.client.messages.create_calls
    assert len(calls) == 3
    assert markers_in(calls[0]["messages"]) == 0
    assert markers_in(calls[1]["messages"]) == 1
    assert markers_in(calls[2]["messages"]) == 1


def test_empty_text_blocks_are_stripped_from_replayed_assistant_turns():
    tool_use = _tool_use_block("pubmed", "t1")
    first = _message([_text_block("   "), tool_use], stop_reason="tool_use")
    provider = _provider_with(create_responses=[first, _message([], stop_reason="end_turn")])
    transcript = Transcript()
    transcript.add_user_text("hello")

    r1 = provider.create(system="SYS", transcript=transcript, tools=[], max_tokens=100)
    transcript.add_assistant(r1)
    transcript.add_tool_results([ToolResult(tool_call_id="t1", content="result1")])

    provider.create(system="SYS", transcript=transcript, tools=[], max_tokens=100)

    second_call_messages = provider.client.messages.create_calls[1]["messages"]
    assistant_message = next(m for m in second_call_messages if m["role"] == "assistant")
    assert all(getattr(b, "type", None) != "text" or b.text.strip() for b in assistant_message["content"])
