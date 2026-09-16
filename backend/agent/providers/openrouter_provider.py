"""OpenRouter's OpenAI-compatible chat-completions API behind the
LLMProvider interface — the required BYOK path when no Anthropic key is
supplied. OpenRouter's free tier needs no credit card to sign up (see
frontend/src/components/OnboardingDialog.tsx), but it's a per-account
allowance (50 requests/day free, 1,000/day after ever buying $10 of credits
once) — there is deliberately no platform-held OpenRouter key funding every
visitor from one shared allowance; each user brings their own.

Prompt caching: the system prompt is sent as a text part carrying
`cache_control: {"type": "ephemeral"}` — OpenRouter forwards that to the
providers that take an explicit breakpoint (Anthropic, Gemini) and ignores it
for the rest; OpenAI-, DeepSeek- and Grok-hosted models cache the shared
prefix automatically. Whatever was served from cache comes back in
`usage.prompt_tokens_details.cached_tokens` and is reported as
`cache_read_input_tokens`, same field the Anthropic provider fills.
A provider that rejects the content-part array gets one plain-string retry
(see `_call_with_retry`) so caching can never be what kills a run.
429s (rate/daily limits) are the *normal* failure mode on a free tier, not
an edge case, so retry-with-backoff is built in rather than left to the
caller; what still fails after that is FallbackProvider's business.
"""
from __future__ import annotations

import json
import time

from openai import BadRequestError, OpenAI, RateLimitError

from backend.agent.providers.base import LLMProvider, LLMResponse, ToolCall, Transcript

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0


def _tool_specs(tools: list[dict]) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
        }
        for t in tools
    ]


def _usage_dict(usage) -> dict:
    """OpenAI-style usage -> the provider-agnostic dict. Cached prompt tokens
    (OpenRouter: usage.prompt_tokens_details.cached_tokens) land in
    cache_read_input_tokens; they are a subset of prompt_tokens, not extra."""
    if not usage:
        return {}
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details is not None else 0
    if isinstance(details, dict):
        cached = details.get("cached_tokens", 0)
    return {
        "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": cached or 0,
    }


def _safe_json(raw: str) -> dict:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    @staticmethod
    def _assistant_message(response: LLMResponse) -> dict:
        """Rebuild one assistant turn in OpenAI wire format from the
        provider-neutral fields — never from `response.raw`, which holds
        whichever provider wrote the turn. A run can switch providers
        mid-way (providers/fallback.py), so this transcript may have been
        written by the Anthropic adapter."""
        message: dict = {"role": "assistant", "content": response.text or ""}
        if response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.input)},
                }
                for call in response.tool_calls
            ]
        return message

    @staticmethod
    def _to_native_messages(system: str, transcript: Transcript) -> list[dict]:
        messages: list[dict] = []
        if system:
            # A content part rather than a bare string, so the cache
            # breakpoint can ride on it (see module docstring).
            messages.append(
                {"role": "system", "content": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
            )
        # The newest tool result carries the second breakpoint and the
        # previous one gives it up, so the cached prefix grows with the
        # transcript instead of pinning an early turn — same rolling scheme
        # as AnthropicProvider, and the ACT loop resends the whole
        # conversation every turn, so this is where the saving is.
        last_tool_message: dict | None = None
        for turn in transcript.turns:
            if turn["role"] == "user":
                messages.append({"role": "user", "content": turn["text"]})
            elif turn["role"] == "assistant":
                messages.append(OpenRouterProvider._assistant_message(turn["response"]))
            elif turn["role"] == "tool_results":
                for r in turn["results"]:
                    messages.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content})
                if turn["results"]:
                    if last_tool_message is not None:
                        last_tool_message["content"] = last_tool_message["content"][0]["text"]
                    last_tool_message = messages[-1]
                    last_tool_message["content"] = [
                        {"type": "text", "text": last_tool_message["content"], "cache_control": {"type": "ephemeral"}}
                    ]
        return messages

    @staticmethod
    def _without_cache_control(messages: list[dict]) -> list[dict]:
        """The same messages with every content-part array flattened back to
        a plain string — i.e. the request as it looked before prompt caching."""
        plain = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, list):
                message = {**message, "content": "".join(part.get("text", "") for part in content)}
            plain.append(message)
        return plain

    def _call_with_retry(self, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return self.client.chat.completions.create(**kwargs)
            except RateLimitError:
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
            except BadRequestError:
                # Caching is an optimization; it is never worth a dead run.
                # OpenRouter fans requests out to many upstreams, and the
                # content-part array that carries `cache_control` is not
                # something every one of them accepts. If a 400 arrives and
                # we sent parts, retry once with plain strings and continue
                # uncached rather than failing the run. A 400 for any other
                # reason re-raises unchanged on that second attempt.
                messages = kwargs.get("messages") or []
                if not any(isinstance(m.get("content"), list) for m in messages):
                    raise
                return self.client.chat.completions.create(
                    **{**kwargs, "messages": self._without_cache_control(messages)}
                )

    def _normalize(self, response) -> LLMResponse:
        message = response.choices[0].message
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, input=_safe_json(tc.function.arguments))
            for tc in raw_tool_calls
        ]
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=message.content or "",
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=_usage_dict(usage),
            model=getattr(response, "model", "") or self.model,
            raw={
                "role": "assistant",
                "content": message.content,
                **({"tool_calls": [tc.model_dump() for tc in raw_tool_calls]} if raw_tool_calls else {}),
            },
        )

    def create(self, system: str, transcript: Transcript, tools: list[dict], max_tokens: int) -> LLMResponse:
        kwargs: dict = {}
        specs = _tool_specs(tools)
        if specs:
            kwargs["tools"] = specs
        response = self._call_with_retry(
            model=self.model,
            max_tokens=max_tokens,
            messages=self._to_native_messages(system, transcript),
            **kwargs,
        )
        return self._normalize(response)

    def stream(self, system: str, transcript: Transcript, max_tokens: int, on_chunk) -> LLMResponse:
        """Collects everything a turn can carry, not just `delta.content`.

        Reading content alone made this path lie in two directions. Models
        that stream their answer into `delta.reasoning` (common on the free
        roster) came back as an empty response with `stop_reason: "end_turn"`
        — a silent blank report. And a turn that was really a tool call, or
        was truncated at `max_tokens`, reported the same cheerful
        "end_turn". `create()`'s `_normalize` always handled all three; this
        is the streaming path catching up."""
        stream = self._call_with_retry(
            model=self.model,
            max_tokens=max_tokens,
            messages=self._to_native_messages(system, transcript),
            stream=True,
            stream_options={"include_usage": True},
        )
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        partial_calls: dict[int, dict] = {}
        finish_reason = None
        usage = None
        model_name = self.model
        for chunk in stream:
            if getattr(chunk, "model", None):
                model_name = chunk.model
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            if getattr(delta, "content", None):
                text_parts.append(delta.content)
                on_chunk(delta.content)
            else:
                reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_parts.append(reasoning)
                    on_chunk(reasoning)
            for call_delta in getattr(delta, "tool_calls", None) or []:
                slot = partial_calls.setdefault(getattr(call_delta, "index", 0), {"id": "", "name": "", "arguments": ""})
                if getattr(call_delta, "id", None):
                    slot["id"] = call_delta.id
                function = getattr(call_delta, "function", None)
                if function is not None:
                    if getattr(function, "name", None):
                        slot["name"] = function.name
                    if getattr(function, "arguments", None):
                        slot["arguments"] += function.arguments

        tool_calls = [
            ToolCall(id=slot["id"], name=slot["name"], input=_safe_json(slot["arguments"]))
            for _, slot in sorted(partial_calls.items())
            if slot["name"]
        ]
        # Reasoning is a fallback body, never an addition: when real content
        # arrived, the reasoning trace is not part of the answer.
        text = "".join(text_parts) or "".join(reasoning_parts)
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else (finish_reason or "end_turn"),
            usage=_usage_dict(usage),
            model=model_name,
            raw={"role": "assistant", "content": text},
        )
