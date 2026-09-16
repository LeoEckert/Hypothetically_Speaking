"""The two LLM adapters must be interchangeable mid-run.

`FallbackProvider` hands one provider's `Transcript` to the other one the
moment it switches, so each adapter has to be able to render a conversation
*any* adapter wrote. That only works if the native message list is rebuilt
from `LLMResponse`'s provider-neutral fields (`text` + `tool_calls`) rather
than from `raw`, which is one provider's private wire format.

These tests also pin the prompt-cache breakpoints in place, because the
rebuild touches the exact code that places them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from backend.agent.providers.base import LLMResponse, ToolCall, ToolResult, Transcript  # noqa: E402
from backend.agent.providers.openrouter_provider import OpenRouterProvider  # noqa: E402

TOOLS = [
    {"name": "pubmed", "description": "search", "input_schema": {"type": "object"}},
    {"name": "open_targets", "description": "targets", "input_schema": {"type": "object"}},
]


def _openrouter_style_turn(text: str, call_id: str) -> LLMResponse:
    """What OpenRouterProvider._normalize() produces: an OpenAI message dict
    in `raw`, and `call_…` tool-call ids."""
    return LLMResponse(
        text=text,
        tool_calls=[ToolCall(id=call_id, name="pubmed", input={"query": "sirt1"})],
        stop_reason="tool_use",
        model="some/free-model:free",
        raw={
            "role": "assistant",
            "content": text,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "pubmed", "arguments": '{"query": "sirt1"}'}}
            ],
        },
    )


def _anthropic_style_turn(text: str, call_id: str) -> LLMResponse:
    """What AnthropicProvider._normalize() produces: a list of SDK content
    blocks in `raw`, and `toolu_…` ids."""

    class _Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    return LLMResponse(
        text=text,
        tool_calls=[ToolCall(id=call_id, name="pubmed", input={"query": "sirt1"})],
        stop_reason="tool_use",
        model="claude-sonnet-5",
        raw=[
            _Block(type="text", text=text),
            _Block(type="tool_use", id=call_id, name="pubmed", input={"query": "sirt1"}),
        ],
    )


def _transcript(assistant_turn: LLMResponse, call_id: str) -> Transcript:
    transcript = Transcript()
    transcript.add_user_text("Does SIRT1 activation extend healthspan?")
    transcript.add_assistant(assistant_turn)
    transcript.add_tool_results([ToolResult(tool_call_id=call_id, content="PMID:1 ...")])
    return transcript


# --- Cross-provider rendering (the bug FallbackProvider hits the moment it fires) ---


def test_anthropic_renders_a_transcript_written_by_openrouter():
    call_id = "call_abc123"
    messages = AnthropicProvider._to_native_messages(_transcript(_openrouter_style_turn("Looking it up.", call_id), call_id))

    assistant = next(m for m in messages if m["role"] == "assistant")
    assert isinstance(assistant["content"], list)
    assert all(isinstance(block, dict) for block in assistant["content"]), (
        "an OpenAI message dict must not be iterated into its own key names"
    )
    assert {b["type"] for b in assistant["content"]} == {"text", "tool_use"}
    text_block = next(b for b in assistant["content"] if b["type"] == "text")
    assert text_block["text"] == "Looking it up."
    tool_block = next(b for b in assistant["content"] if b["type"] == "tool_use")
    assert (tool_block["id"], tool_block["name"], tool_block["input"]) == (call_id, "pubmed", {"query": "sirt1"})


def test_openrouter_renders_a_transcript_written_by_anthropic():
    call_id = "toolu_abc123"
    messages = OpenRouterProvider._to_native_messages("", _transcript(_anthropic_style_turn("Looking it up.", call_id), call_id))

    assistant = next(m for m in messages if m["role"] == "assistant")
    assert isinstance(assistant, dict) and assistant["content"] == "Looking it up."
    assert [tc["id"] for tc in assistant["tool_calls"]] == [call_id]
    assert assistant["tool_calls"][0]["function"]["name"] == "pubmed"
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == call_id


def test_tool_result_ids_always_match_the_assistant_turn_that_asked():
    """Anthropic rejects a tool_result whose tool_use_id has no matching
    tool_use block — the id has to survive a provider switch unchanged."""
    for call_id, turn in (("call_x", _openrouter_style_turn("t", "call_x")), ("toolu_x", _anthropic_style_turn("t", "toolu_x"))):
        messages = AnthropicProvider._to_native_messages(_transcript(turn, call_id))
        tool_use_ids = {
            b["id"] for m in messages if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_use"
        }
        result_ids = {
            b["tool_use_id"]
            for m in messages
            if m["role"] == "user" and isinstance(m["content"], list)
            for b in m["content"]
            if b.get("type") == "tool_result"
        }
        assert result_ids and result_ids <= tool_use_ids, f"orphaned tool_result for {call_id}"


def test_an_assistant_turn_with_no_raw_still_renders():
    """A turn rebuilt from a stored run, or one a provider left `raw=None` on,
    must not crash the next request."""
    transcript = Transcript()
    transcript.add_user_text("q")
    transcript.add_assistant(LLMResponse(text="plain answer", model="m"))
    assert AnthropicProvider._to_native_messages(transcript)[-1] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "plain answer"}],
    }
    assert OpenRouterProvider._to_native_messages("", transcript)[-1] == {"role": "assistant", "content": "plain answer"}


def test_an_empty_assistant_text_block_is_still_dropped_for_anthropic():
    """The 400 guard this provider has always had ("text content blocks must
    be non-empty") must survive the rebuild."""
    transcript = Transcript()
    transcript.add_user_text("q")
    transcript.add_assistant(
        LLMResponse(text="   ", tool_calls=[ToolCall(id="c1", name="pubmed", input={})], stop_reason="tool_use")
    )
    content = AnthropicProvider._to_native_messages(transcript)[-1]["content"]
    assert [b["type"] for b in content] == ["tool_use"]


# --- Prompt caching breakpoints (must survive the rebuild above) ---


def _cache_marked(blocks) -> list:
    return [b for b in blocks if isinstance(b, dict) and "cache_control" in b]


def test_anthropic_marks_the_system_prompt_and_the_last_tool_spec():
    assert _cache_marked(AnthropicProvider._system_blocks("SYSTEM")) == [
        {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    ]
    specs = AnthropicProvider._tool_specs(TOOLS)
    assert [s["name"] for s in _cache_marked(specs)] == ["open_targets"], "only the last tool spec is marked"
    assert AnthropicProvider._tool_specs([]) is None


def test_anthropic_tool_result_cache_breakpoint_rolls_forward():
    """Only the newest tool-result block carries the breakpoint; the previous
    one is un-marked, so a long run never exceeds Anthropic's 4-breakpoint cap."""
    transcript = Transcript()
    transcript.add_user_text("q")
    for i in range(3):
        transcript.add_assistant(
            LLMResponse(text=f"turn {i}", tool_calls=[ToolCall(id=f"c{i}", name="pubmed", input={})], stop_reason="tool_use")
        )
        transcript.add_tool_results([ToolResult(tool_call_id=f"c{i}", content=f"result {i}")])

    messages = AnthropicProvider._to_native_messages(transcript)
    tool_result_blocks = [
        b for m in messages if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]
    ]
    marked = _cache_marked(tool_result_blocks)
    assert len(marked) == 1, "exactly one rolling breakpoint, not one per turn"
    assert marked[0]["content"] == "result 2", "the breakpoint sits on the newest tool result"

    # system + last tool spec + one rolling tool result = 3, under the cap of 4.
    total = len(_cache_marked(AnthropicProvider._system_blocks("SYSTEM"))) + len(
        _cache_marked(AnthropicProvider._tool_specs(TOOLS))
    ) + len(marked)
    assert total == 3


def test_openrouter_tool_result_cache_breakpoint_rolls_forward():
    transcript = Transcript()
    transcript.add_user_text("q")
    for i in range(3):
        transcript.add_assistant(
            LLMResponse(text=f"turn {i}", tool_calls=[ToolCall(id=f"c{i}", name="pubmed", input={})], stop_reason="tool_use")
        )
        transcript.add_tool_results([ToolResult(tool_call_id=f"c{i}", content=f"result {i}")])

    messages = OpenRouterProvider._to_native_messages("SYSTEM", transcript)
    assert _cache_marked(messages[0]["content"]), "system prompt keeps its breakpoint"

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    marked = [m for m in tool_msgs if isinstance(m["content"], list) and _cache_marked(m["content"])]
    assert len(marked) == 1 and marked[0]["tool_call_id"] == "c2"
    assert all(isinstance(m["content"], str) for m in tool_msgs if m is not marked[0]), (
        "older tool results stay plain strings — only the rolling one is a content-part array"
    )
