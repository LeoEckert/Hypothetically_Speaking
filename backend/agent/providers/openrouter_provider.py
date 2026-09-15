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
429s (rate/daily limits) are the *normal* failure mode on a free tier, not
an edge case, so retry-with-backoff is built in rather than left to the
caller; what still fails after that is FallbackProvider's business.
"""
from __future__ import annotations

import json
import time

from openai import OpenAI, RateLimitError

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
    def _to_native_messages(system: str, transcript: Transcript) -> list[dict]:
        messages: list[dict] = []
        if system:
            # A content part rather than a bare string, so the cache
            # breakpoint can ride on it (see module docstring).
            messages.append(
                {"role": "system", "content": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
            )
        for turn in transcript.turns:
            if turn["role"] == "user":
                messages.append({"role": "user", "content": turn["text"]})
            elif turn["role"] == "assistant":
                messages.append(turn["response"].raw)
            elif turn["role"] == "tool_results":
                for r in turn["results"]:
                    messages.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content})
        return messages

    def _call_with_retry(self, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return self.client.chat.completions.create(**kwargs)
            except RateLimitError:
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))

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
        stream = self._call_with_retry(
            model=self.model,
            max_tokens=max_tokens,
            messages=self._to_native_messages(system, transcript),
            stream=True,
            stream_options={"include_usage": True},
        )
        text_parts: list[str] = []
        usage = None
        model_name = self.model
        for chunk in stream:
            if chunk.model:
                model_name = chunk.model
            if chunk.choices and chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.content
                text_parts.append(delta)
                on_chunk(delta)
            if getattr(chunk, "usage", None):
                usage = chunk.usage
        text = "".join(text_parts)
        return LLMResponse(
            text=text,
            tool_calls=[],
            stop_reason="end_turn",
            usage=_usage_dict(usage),
            model=model_name,
            raw={"role": "assistant", "content": text},
        )
