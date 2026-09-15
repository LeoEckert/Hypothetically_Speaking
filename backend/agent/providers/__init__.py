"""Provider selection: an Anthropic key (from the request, i.e. BYOK, or a
platform env var) selects Claude; otherwise every run falls back to the
shared free-tier Groq default. This is the one place that decides which
provider a run uses — loop.py, adapters.py and evaluate.py all call this
instead of constructing an SDK client directly.
"""
from __future__ import annotations

import os

from backend.agent.providers.anthropic_provider import AnthropicProvider
from backend.agent.providers.base import LLMProvider, LLMResponse, ToolCall, ToolResult, Transcript
from backend.agent.providers.groq_provider import GroqProvider

__all__ = ["LLMProvider", "LLMResponse", "ToolCall", "ToolResult", "Transcript", "get_provider", "NoProviderAvailable"]

_ANTHROPIC_MAIN_MODEL = "claude-sonnet-5"
_ANTHROPIC_FAST_MODEL = "claude-haiku-4-5-20251001"
# Fast, strong tool-calling open models on Groq's free tier (re-verify model
# names/limits periodically — Groq's free-tier lineup changes; see CLAUDE.md).
_GROQ_MAIN_MODEL_DEFAULT = "openai/gpt-oss-120b"
_GROQ_FAST_MODEL_DEFAULT = "llama-3.1-8b-instant"


class NoProviderAvailable(RuntimeError):
    """Neither an Anthropic key (BYOK or platform) nor a platform GROQ_API_KEY
    is configured — there is genuinely no LLM to run this request against."""


def get_provider(api_keys: dict[str, str] | None = None, tier: str = "main") -> LLMProvider:
    """`tier`: "main" for the primary loop/report-writing work, "fast" for
    cheaper sub-tasks (grounding's L1 probe) — mirrors the pre-existing
    Sonnet-vs-Haiku cost tiering, now generalized across providers.
    `api_keys` are per-request, user-supplied overrides (see RunRequest.api_keys
    in backend/server/app.py); a platform env var is the fallback for each."""
    api_keys = api_keys or {}
    user_anthropic_key = api_keys.get("ANTHROPIC_API_KEY")
    anthropic_key = user_anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        model = (
            os.environ.get("ANTHROPIC_MODEL", _ANTHROPIC_MAIN_MODEL)
            if tier == "main"
            else os.environ.get("GROUNDING_FAST_MODEL", _ANTHROPIC_FAST_MODEL)
        )
        provider = AnthropicProvider(api_key=anthropic_key, model=model)
        provider.key_source = "user" if user_anthropic_key else "platform"
        return provider

    user_groq_key = api_keys.get("GROQ_API_KEY")
    groq_key = user_groq_key or os.environ.get("GROQ_API_KEY")
    if not groq_key:
        raise NoProviderAvailable(
            "No Anthropic key (yours or the platform's) and no Groq key configured — "
            "add your own key in Settings, or the platform's shared free-tier key is missing."
        )
    model = (
        os.environ.get("GROQ_MODEL", _GROQ_MAIN_MODEL_DEFAULT)
        if tier == "main"
        else os.environ.get("GROQ_FAST_MODEL", _GROQ_FAST_MODEL_DEFAULT)
    )
    provider = GroqProvider(api_key=groq_key, model=model)
    provider.key_source = "user" if user_groq_key else "platform"
    return provider
