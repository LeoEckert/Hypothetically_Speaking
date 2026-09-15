"""Anthropic Messages API behind the LLMProvider interface. Owns everything
Anthropic-specific: content-block conversion, prompt caching (cache_control),
and the empty-text-block guard — none of that leaks into loop.py/adapters.py.
"""
from __future__ import annotations

from anthropic import Anthropic

from backend.agent.providers.base import LLMProvider, LLMResponse, ToolCall, Transcript


def _strip_empty_text_blocks(content_blocks):
    """Claude sometimes returns a text block with empty/whitespace-only text
    alongside a tool_use or thinking block in the same turn. Resending that
    verbatim on the next request gets rejected with a 400 ("text content
    blocks must be non-empty"), which otherwise aborts the whole run. Drop
    only truly empty text blocks; everything else passes through untouched."""
    return [b for b in content_blocks if not (getattr(b, "type", None) == "text" and not b.text.strip())]


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str) -> None:
        self.client = Anthropic(api_key=api_key)
        self.model = model

    @staticmethod
    def _system_blocks(system: str) -> list[dict]:
        if not system:
            return []
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    @staticmethod
    def _tool_specs(tools: list[dict]) -> list[dict] | None:
        if not tools:
            return None
        # The tool roster is identical on every call this run — cache-mark
        # the last spec so "cache everything up to here" is pinned once.
        return [*tools[:-1], {**tools[-1], "cache_control": {"type": "ephemeral"}}]

    @staticmethod
    def _to_native_messages(transcript: Transcript) -> list[dict]:
        messages: list[dict] = []
        last_tool_result_block: dict | None = None
        for turn in transcript.turns:
            if turn["role"] == "user":
                messages.append({"role": "user", "content": turn["text"]})
            elif turn["role"] == "assistant":
                response: LLMResponse = turn["response"]
                messages.append({"role": "assistant", "content": _strip_empty_text_blocks(response.raw)})
            elif turn["role"] == "tool_results":
                content = [
                    {"type": "tool_result", "tool_use_id": r.tool_call_id, "content": r.content}
                    for r in turn["results"]
                ]
                if content:
                    if last_tool_result_block is not None:
                        last_tool_result_block.pop("cache_control", None)
                    content[-1]["cache_control"] = {"type": "ephemeral"}
                    last_tool_result_block = content[-1]
                messages.append({"role": "user", "content": content})
        return messages

    @staticmethod
    def _normalize(response) -> LLMResponse:
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input)
            for b in response.content
            if getattr(b, "type", None) == "tool_use"
        ]
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage={
                key: getattr(usage, key, 0) or 0
                for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            }
            if usage
            else {},
            model=getattr(response, "model", "") or "",
            raw=response.content,
        )

    def create(self, system: str, transcript: Transcript, tools: list[dict], max_tokens: int) -> LLMResponse:
        kwargs: dict = {}
        tool_specs = self._tool_specs(tools)
        if tool_specs:
            kwargs["tools"] = tool_specs
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=self._system_blocks(system),
            messages=self._to_native_messages(transcript),
            **kwargs,
        )
        return self._normalize(response)

    def stream(self, system: str, transcript: Transcript, max_tokens: int, on_chunk) -> LLMResponse:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=self._system_blocks(system),
            messages=self._to_native_messages(transcript),
        ) as stream:
            for chunk in stream.text_stream:
                on_chunk(chunk)
            return self._normalize(stream.get_final_message())
