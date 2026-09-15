"""Provider selection: an Anthropic key (from the request, i.e. BYOK, or a
local-dev env var) selects Claude; otherwise an OpenRouter key (same) selects
OpenRouter. There is deliberately no platform-held key funding every visitor
from one shared allowance for either provider — every real user brings their
own, guided by the frontend's required onboarding popup
(frontend/src/components/OnboardingDialog.tsx). The env-var fallback here
exists only for local dev convenience (scripts/run_demo.py, manual testing);
an operator can also optionally set a platform key via the admin dashboard
(backend/agent/admin.py's ROTATABLE_KEYS) if they choose to, but nothing in
this app relies on one existing. This is the one place that decides which
provider a run uses — loop.py, adapters.py and evaluate.py all call this
instead of constructing an SDK client directly.
"""
from __future__ import annotations

import os

from backend.agent.providers.anthropic_provider import AnthropicProvider
from backend.agent.providers.base import LLMProvider, LLMResponse, ToolCall, ToolResult, Transcript
from backend.agent.providers.openrouter_provider import OpenRouterProvider

__all__ = ["LLMProvider", "LLMResponse", "ToolCall", "ToolResult", "Transcript", "get_provider", "NoProviderAvailable"]

_ANTHROPIC_MAIN_MODEL = "claude-sonnet-5"
_ANTHROPIC_FAST_MODEL = "claude-haiku-4-5-20251001"
# OpenRouter's auto-router picks a free model that supports what the request
# needs (including tool calling) from its rotating free-tier lineup — re-verify
# this actually works reliably for tool-calling at implementation/test time; if
# not, pin an explicit named free model here instead (see CLAUDE.md).
_OPENROUTER_MAIN_MODEL_DEFAULT = "openrouter/auto"
_OPENROUTER_FAST_MODEL_DEFAULT = "openrouter/auto"


class NoProviderAvailable(RuntimeError):
    """Neither an Anthropic key nor an OpenRouter key is configured (BYOK or
    a local-dev env var) — there is genuinely no LLM to run this request
    against. Both are free to obtain (OpenRouter needs no credit card) —
    this should only happen if a caller bypassed the frontend's required
    onboarding popup."""


def get_provider(api_keys: dict[str, str] | None = None, tier: str = "main") -> LLMProvider:
    """`tier`: "main" for the primary loop/report-writing work, "fast" for
    cheaper sub-tasks (grounding's L1 probe) — mirrors the pre-existing
    Sonnet-vs-Haiku cost tiering, now generalized across providers.
    `api_keys` are per-request, user-supplied overrides (see RunRequest.api_keys
    in backend/server/app.py) — this is how BYOK actually reaches a run; the
    os.environ fallback below is a local-dev convenience only, not how
    production is meant to be configured (see module docstring)."""
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

    user_openrouter_key = api_keys.get("OPENROUTER_API_KEY")
    openrouter_key = user_openrouter_key or os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise NoProviderAvailable(
            "No LLM key configured — add a free OpenRouter key (no credit card, "
            "openrouter.ai/keys) or your own Anthropic key in Settings to run this."
        )
    model = (
        os.environ.get("OPENROUTER_MODEL", _OPENROUTER_MAIN_MODEL_DEFAULT)
        if tier == "main"
        else os.environ.get("OPENROUTER_FAST_MODEL", _OPENROUTER_FAST_MODEL_DEFAULT)
    )
    provider = OpenRouterProvider(api_key=openrouter_key, model=model)
    provider.key_source = "user" if user_openrouter_key else "platform"
    return provider
