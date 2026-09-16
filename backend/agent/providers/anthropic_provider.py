"""Anthropic Messages API behind the LLMProvider interface. Owns everything
Anthropic-specific: content-block conversion, prompt caching (cache_control),
and the empty-text-block guard — none of that leaks into loop.py/adapters.py.

Every request is built from the provider-neutral `Transcript`/`LLMResponse`
fields, so this adapter can pick up a conversation another adapter started
(see providers/fallback.py).
"""
from __future__ import annotations

from anthropic import Anthropic

from backend.agent.providers.base import LLMProvider, LLMResponse, ToolCall, Transcript


def _assistant_blocks(response: LLMResponse) -> list[dict]:
    """Rebuild one assistant turn as Anthropic content blocks from the
    provider-neutral fields of `LLMResponse` — never from `response.raw`,
    which holds whichever provider produced the turn's own wire format. A
    run can switch providers mid-way (providers/fallback.py), so the
    transcript we are handed may well have been written by the OpenAI-shaped
    adapter; rebuilding is what makes the two interchangeable.

    Dropping empty text also keeps an old guard alive for free: Claude
    sometimes returns a whitespace-only text block next to a tool_use block,
    and resending that verbatim is a 400 ("text content blocks must be
    non-empty") that used to abort the whole run."""
    blocks: list[dict] = []
    if response.text and response.text.strip():
        blocks.append({"type": "text", "text": response.text})
    blocks.extend(
        {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
        for call in response.tool_calls
    )
    return blocks


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str) -> None:
        if not model or not model.strip():
            # Fail here with the cause named, not later as the API's
            # "model: String should have at least 1 character".
            raise ValueError(
                "Anthropic model name is empty — check the ANTHROPIC_MODEL / GROUNDING_FAST_MODEL env vars"
            )
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
                blocks = _assistant_blocks(turn["response"])
                # An assistant turn with neither text nor tool calls has no
                # valid representation here — the API rejects empty content —
                # so it is left out rather than sent as a broken message.
                if blocks:
                    messages.append({"role": "assistant", "content": blocks})
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
