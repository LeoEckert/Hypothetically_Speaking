"""Provider-agnostic LLM seam.

`backend/agent/loop.py` and `backend/grounding/adapters.py` both need to run
against either Anthropic's Messages API (tool-use, content blocks, prompt
caching) or an OpenAI-compatible chat-completions API (OpenRouter, selected
when no Anthropic key is supplied) without branching on which one is in use.
Everything provider-specific — content-block shapes, cache_control,
tool-call wire formats — lives inside the two concrete providers; callers only
ever see `LLMResponse` and `Transcript`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ToolResult:
    tool_call_id: str
    content: str


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "tool_use", or anything else meaning "done talking"
    usage: dict = field(
        default_factory=lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    )
    model: str = ""
    # Opaque per-provider representation of this assistant turn (Anthropic
    # content blocks, or an OpenAI-style message dict) — round-tripped back
    # into that same provider's next call via Transcript, never inspected by
    # callers outside the provider that produced it.
    raw: object = None


class Transcript:
    """Provider-agnostic conversation history. Callers (loop.py, adapters.py)
    build and mutate this; each LLMProvider converts it to/from its own wire
    format inside create()/stream(). A turn is one of: user text, an assistant
    response (as returned by a provider), or the tool results answering the
    most recent assistant turn's tool calls."""

    def __init__(self) -> None:
        self.turns: list[dict] = []

    def add_user_text(self, text: str) -> None:
        self.turns.append({"role": "user", "text": text})

    def add_assistant(self, response: LLMResponse) -> None:
        self.turns.append({"role": "assistant", "response": response})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self.turns.append({"role": "tool_results", "results": results})


class LLMProvider:
    """Implemented by providers.anthropic_provider.AnthropicProvider and
    providers.openrouter_provider.OpenRouterProvider."""

    name: str  # "anthropic" | "openrouter" — set by get_provider(), used by costs.py
    model: str
    # "user" (BYOK) or "platform" (a local-dev env var — see providers/__init__.py's
    # module docstring on why production shouldn't have one). Set by get_provider().
    key_source: str = "platform"

    def create(self, system: str, transcript: Transcript, tools: list[dict], max_tokens: int) -> LLMResponse:
        raise NotImplementedError

    def stream(self, system: str, transcript: Transcript, max_tokens: int, on_chunk) -> LLMResponse:
        """`on_chunk(text_delta: str)` fires as text streams in; returns the
        same normalized LLMResponse as create() once the turn is complete."""
        raise NotImplementedError

    def complete(self, prompt: str, max_tokens: int) -> LLMResponse:
        """Single-turn, no system prompt, no tools — what the grounding stage
        and the evaluate/judge pass need (they parse a fenced JSON block out
        of plain text rather than using tool-use)."""
        transcript = Transcript()
        transcript.add_user_text(prompt)
        return self.create(system="", transcript=transcript, tools=[], max_tokens=max_tokens)
