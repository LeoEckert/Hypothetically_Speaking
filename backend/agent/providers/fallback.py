"""Try the free path first, keep the run alive on the paid one.

When a request carries both keys, the run starts on the primary provider
(Claude — see providers/__init__.py) and only moves to the fallback if the
primary actually fails: a 429 that survived the provider's own retries, a
credit-exhaustion 402, a model that vanished (404), a 5xx, a connection or
read timeout — or a completion that came back with nothing in it. The switch
is sticky for the rest of the run: a transcript half-written by one model is
not bounced back and forth, and every later call (grounding, PLAN, ACT,
REVISE, REPORT, evaluate) goes to the fallback.

An empty completion counts as a failure because it is the one that never
raises. A 200 OK carrying no text and no tool calls is not a usable turn —
it is how a model that streamed only reasoning, or truncated before emitting
content, comes back — and treating it as success is what put blank reports
in front of users. A tool-use turn legitimately has no prose, so both halves
are required: no text *and* no tool calls.

Handing another provider's transcript over only works because each adapter
rebuilds its native messages from the provider-neutral fields of
`LLMResponse` rather than from `raw` — see providers/base.py.

`name`, `model` and `key_source` always describe the provider currently in
use, so costs.py and the cost panel attribute the run correctly; per-response
`LLMResponse.model` already carries which model produced each turn.
"""

from __future__ import annotations

import sys

import openai

from backend.agent.providers.base import LLMProvider, LLMResponse, Transcript

# What counts as "OpenRouter failed" rather than "the request was wrong":
# rate/daily limits, credit exhaustion, an unavailable model, server errors,
# and transport failures. A 400/401/403 on the primary is left to propagate —
# a rejected key or a malformed request would be just as wrong on the fallback.
FALLBACK_STATUS_CODES = {402, 404, 408, 409, 429, 500, 502, 503, 504}


def _should_fall_back(exc: BaseException) -> bool:
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code in FALLBACK_STATUS_CODES
    return False


class FallbackProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.active = primary
        self.fallback_reason: str | None = None

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.active.name

    @property
    def model(self) -> str:  # type: ignore[override]
        return self.active.model

    @property
    def key_source(self) -> str:  # type: ignore[override]
        return self.active.key_source

    @property
    def switched(self) -> bool:
        return self.active is self.fallback

    @staticmethod
    def _is_empty(response) -> bool:
        """No prose and no tool calls — nothing the caller can use."""
        return not (getattr(response, "text", "") or "").strip() and not getattr(response, "tool_calls", None)

    def _switch(self, reason: str):
        self.fallback_reason = reason
        print(
            f"provider fallback: {self.primary.name} ({self.primary.model}) failed — {reason}; "
            f"continuing on {self.fallback.name} ({self.fallback.model})",
            file=sys.stderr,
        )
        self.active = self.fallback

    def _run(self, call):
        try:
            response = call(self.active)
        except Exception as exc:  # noqa: BLE001 — classified right below
            if self.switched or not _should_fall_back(exc):
                raise
            self._switch(f"{type(exc).__name__}: {str(exc)[:200]}")
            return call(self.active)
        if self._is_empty(response) and not self.switched:
            self._switch("empty completion: no text and no tool calls")
            return call(self.active)
        return response

    def create(self, system: str, transcript: Transcript, tools: list[dict], max_tokens: int) -> LLMResponse:
        return self._run(lambda p: p.create(system, transcript, tools, max_tokens))

    def stream(self, system: str, transcript: Transcript, max_tokens: int, on_chunk) -> LLMResponse:
        # A stream that dies mid-way may already have emitted chunks; the
        # fallback's chunks then continue the same text — the reader only
        # ever sees one growing string, which is the right thing for the
        # status bar and the report.
        return self._run(lambda p: p.stream(system, transcript, max_tokens, on_chunk))

    def complete(self, prompt: str, max_tokens: int) -> LLMResponse:
        return self._run(lambda p: p.complete(prompt, max_tokens))
