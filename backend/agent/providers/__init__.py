"""Provider selection. Every key here is BYOK — from the request (the
frontend's required onboarding popup / Settings) or, for local dev only, an
env var; there is deliberately no platform-held key funding every visitor
from one shared allowance (see the module docstring history in git and
CLAUDE.md). An operator can still optionally set a platform key via the admin
dashboard (backend/agent/admin.py's ROTATABLE_KEYS), but nothing relies on it.

Which provider a run gets:

- only an OpenRouter key -> OpenRouterProvider (free models);
- only an Anthropic key  -> AnthropicProvider, model per
  backend/config/models.toml for this deployment (see model_policy.py);
- both                   -> FallbackProvider: Claude first, and the run moves
  to OpenRouter's free models only if Claude fails (rate limit, credit
  exhaustion, 5xx, transport, or a completion with nothing in it) — sticky
  for the rest of that run.

Claude leads when both keys are present because the free roster could not be
relied on for the hardest generation in a run, the final report: models there
routinely answered it with an empty completion or with the machine-readable
block alone, which is a quality failure no status code announces.

This is the one place that decides; loop.py, adapters.py and evaluate.py all
call get_provider() instead of constructing an SDK client directly.
"""
from __future__ import annotations

import os

from backend.agent.env import env_str
from backend.agent.model_policy import anthropic_model
from backend.agent.providers.anthropic_provider import AnthropicProvider
from backend.agent.providers.base import LLMProvider, LLMResponse, ToolCall, ToolResult, Transcript
from backend.agent.providers.fallback import FallbackProvider
from backend.agent.providers.openrouter_models import best_free_tool_model
from backend.agent.providers.openrouter_provider import OpenRouterProvider

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "ToolCall",
    "ToolResult",
    "Transcript",
    "FallbackProvider",
    "get_provider",
    "NoProviderAvailable",
]


class NoProviderAvailable(RuntimeError):
    """Neither an Anthropic key nor an OpenRouter key is configured (BYOK or
    a local-dev env var) — there is genuinely no LLM to run this request
    against. Both are free to obtain (OpenRouter needs no credit card) —
    this should only happen if a caller bypassed the frontend's required
    onboarding popup."""


def _openrouter(api_keys: dict[str, str], tier: str, key: str, user_supplied: bool) -> OpenRouterProvider:
    # A per-request pick (frontend Settings model picker, see GET /api/models)
    # rides the same api_keys dict as the keys themselves. It beats the
    # server-side OPENROUTER_MODEL / OPENROUTER_FAST_MODEL env pins, which in
    # turn beat the live best-free-model pick. No default slug is hardcoded:
    # OpenRouter's free roster changes on its own schedule (openrouter_models.py).
    user_model = api_keys.get("OPENROUTER_MODEL")
    env_pin = env_str("OPENROUTER_MODEL") if tier == "main" else env_str("OPENROUTER_FAST_MODEL")
    provider = OpenRouterProvider(api_key=key, model=user_model or env_pin or best_free_tool_model())
    provider.key_source = "user" if user_supplied else "platform"
    return provider


def _anthropic(api_keys: dict[str, str], tier: str, key: str, user_supplied: bool) -> AnthropicProvider:
    provider = AnthropicProvider(api_key=key, model=anthropic_model(tier, api_keys))
    provider.key_source = "user" if user_supplied else "platform"
    return provider


def get_provider(api_keys: dict[str, str] | None = None, tier: str = "main") -> LLMProvider:
    """`tier`: "main" for the primary loop/report-writing work, "fast" for
    cheaper sub-tasks (grounding's L1 probe) — the Sonnet-vs-Haiku cost
    tiering, generalized across providers. `api_keys` are the per-request,
    user-supplied values (RunRequest.api_keys in backend/server/app.py); the
    os.environ fallback is a local-dev convenience only."""
    api_keys = api_keys or {}
    user_openrouter_key = api_keys.get("OPENROUTER_API_KEY")
    openrouter_key = user_openrouter_key or os.environ.get("OPENROUTER_API_KEY")
    user_anthropic_key = api_keys.get("ANTHROPIC_API_KEY")
    anthropic_key = user_anthropic_key or os.environ.get("ANTHROPIC_API_KEY")

    if not openrouter_key and not anthropic_key:
        raise NoProviderAvailable(
            "No LLM key configured — add a free OpenRouter key (no credit card, "
            "openrouter.ai/keys) or your own Anthropic key in Settings to run this."
        )

    openrouter = _openrouter(api_keys, tier, openrouter_key, bool(user_openrouter_key)) if openrouter_key else None
    anthropic = _anthropic(api_keys, tier, anthropic_key, bool(user_anthropic_key)) if anthropic_key else None
    if openrouter and anthropic:
        return FallbackProvider(primary=anthropic, fallback=openrouter)
    return openrouter or anthropic  # type: ignore[return-value]
