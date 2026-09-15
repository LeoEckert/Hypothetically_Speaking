"""Per-run cost/usage accounting across every external API the agent loop
touches. Every dollar figure is either computed from a real, confirmed rate
or explicitly marked unpriced (`rate_configured: False`, `usd: None`) — never
silently invented. See docs/DEPLOY.md / .env.example for the pricing env vars.
"""
from __future__ import annotations

import os

from backend.agent.state import RunState

# Confirmed Anthropic pricing (USD per 1M tokens) as of this writing — re-verify
# against current published pricing before relying on this for real billing,
# prices drift over time.
ANTHROPIC_PRICING_PER_1M = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
# General Anthropic prompt-caching cost model: writing to cache costs ~1.25x
# the input rate, reading from cache costs ~0.1x the input rate.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _pricing_for(model: str) -> dict | None:
    """Dated ids ("claude-haiku-4-5-20251001") price as their family."""
    if model in ANTHROPIC_PRICING_PER_1M:
        return ANTHROPIC_PRICING_PER_1M[model]
    for family, pricing in ANTHROPIC_PRICING_PER_1M.items():
        if model.startswith(family):
            return pricing
    return None


def anthropic_cost_usd(
    model: str, input_tokens: int, output_tokens: int, cache_write_tokens: int, cache_read_tokens: int
) -> tuple[float | None, bool]:
    """Returns (usd, rate_configured). An unrecognized model is never priced
    against another model's rate — it comes back unconfigured instead."""
    pricing = _pricing_for(model)
    if pricing is None:
        return None, False
    usd = (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_write_tokens * pricing["input"] * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * pricing["input"] * CACHE_READ_MULTIPLIER
    ) / 1_000_000
    return usd, True


def nebius_cost_usd(prompt_tokens: int, completion_tokens: int) -> tuple[float | None, bool]:
    price_in = _env_float("NEBIUS_PRICE_PER_1M_INPUT")
    price_out = _env_float("NEBIUS_PRICE_PER_1M_OUTPUT")
    if price_in is None or price_out is None:
        return None, False
    usd = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
    return usd, True


def amass_cost_usd(credits_used: float | None) -> tuple[float | None, bool]:
    price_per_credit = _env_float("AMASS_PRICE_PER_CREDIT")
    if price_per_credit is None or credits_used is None:
        return None, False
    return credits_used * price_per_credit, True


def tavily_cost_usd(live_calls: int) -> tuple[float | None, bool]:
    price_per_call = _env_float("TAVILY_USD_PER_CALL")
    if price_per_call is None:
        return None, False
    return live_calls * price_per_call, True


_FREE_TOOLS = ("open_targets", "pubmed", "clinicaltrials", "genage_drugage", "run_enrichment")


def _key_source(env_var: str, api_keys: dict | None) -> str:
    api_keys = api_keys or {}
    if api_keys.get(env_var):
        return "user"
    if os.environ.get(env_var):
        return "platform"
    return "unset"


def build_cost_summary(state: RunState, provider, api_keys: dict | None = None) -> dict:
    """`provider` is the resolved LLMProvider for this run (or None if no
    provider was ever available — see loop.py's NoProviderAvailable path)."""
    tavily_calls = [t for t in state.trace if t.tool_name == "tavily"]
    tavily_live = sum(1 for t in tavily_calls if not t.mock)
    tavily_mock = len(tavily_calls) - tavily_live

    amass_calls = [t for t in state.trace if t.tool_name == "amass"]
    amass_live = sum(1 for t in amass_calls if not t.mock)
    amass_mock = len(amass_calls) - amass_live
    credits_used = None
    if state.amass_credits_before is not None and state.amass_credits_after is not None:
        credits_used = state.amass_credits_before - state.amass_credits_after

    provider_name = getattr(provider, "name", None)
    model = getattr(provider, "model", "") or ""
    llm_key_source = getattr(provider, "key_source", "unset") if provider else "unset"

    llm_usd, llm_priced, llm_free_tier = 0.0, True, False
    llm_models = []
    # Free-tier status is keyed off the actual model slug, not just the
    # provider name — get_provider() always picks a live ":free" OpenRouter
    # model by default, but an operator can pin OPENROUTER_MODEL to a paid
    # one, and that run must not show a false $0.
    if provider_name == "openrouter" and model.endswith(":free"):
        # A genuinely free tier, not an unknown rate — $0 with rate_configured
        # True, distinct from "we don't know the price" (rate_configured False).
        llm_usd, llm_priced, llm_free_tier = 0.0, True, True
        llm_models = [
            {
                "model": name,
                **tokens,
                "usd": 0.0,
                "rate_configured": True,
            }
            for name, tokens in (state.anthropic_by_model or {}).items()
        ]
    else:
        # Price each Anthropic model at its own rate (Haiku grounding, Sonnet
        # loop); fall back to the run model only for tokens recorded without one.
        by_model = state.anthropic_by_model or (
            {
                model: {
                    "calls": state.anthropic_calls,
                    "input_tokens": state.anthropic_input_tokens,
                    "output_tokens": state.anthropic_output_tokens,
                    "cache_creation_input_tokens": state.anthropic_cache_creation_input_tokens,
                    "cache_read_input_tokens": state.anthropic_cache_read_input_tokens,
                }
            }
            if model
            else {}
        )
        for name, tokens in by_model.items():
            usd, priced = anthropic_cost_usd(
                name if name != "unknown" else model,
                tokens["input_tokens"], tokens["output_tokens"],
                tokens["cache_creation_input_tokens"], tokens["cache_read_input_tokens"],
            )
            llm_models.append({"model": name, **tokens, "usd": usd, "rate_configured": priced})
            if usd is None:
                llm_priced = False
            else:
                llm_usd += usd
        if not llm_priced and all(entry["usd"] is None for entry in llm_models):
            llm_usd = None

    nebius_usd, nebius_priced = nebius_cost_usd(state.nebius_prompt_tokens, state.nebius_completion_tokens)
    amass_usd, amass_priced = amass_cost_usd(credits_used)
    tavily_usd, tavily_priced = tavily_cost_usd(tavily_live)

    free_tools = {
        name: {"calls": sum(1 for t in state.trace if t.tool_name == name)} for name in _FREE_TOOLS
    }

    total_usd = sum(usd for usd in (llm_usd, nebius_usd, amass_usd, tavily_usd) if usd is not None)
    unpriced = [
        name
        for name, priced in (
            ("nebius", nebius_priced),
            ("amass", amass_priced),
            ("tavily", tavily_priced),
        )
        if not priced
    ]

    return {
        # Kept as "anthropic" for frontend/report-JSON compatibility, but this
        # row now reports whichever LLM provider the run actually used —
        # see `provider`/`free_tier`/`key_source` to tell them apart.
        "anthropic": {
            "provider": provider_name,
            "calls": state.anthropic_calls,
            "model": model,
            "input_tokens": state.anthropic_input_tokens,
            "output_tokens": state.anthropic_output_tokens,
            "cache_creation_input_tokens": state.anthropic_cache_creation_input_tokens,
            "cache_read_input_tokens": state.anthropic_cache_read_input_tokens,
            "usd": llm_usd,
            "rate_configured": llm_priced,
            "free_tier": llm_free_tier,
            "key_source": llm_key_source,
            "by_model": llm_models,
        },
        "nebius": {
            "calls": state.nebius_calls,
            "prompt_tokens": state.nebius_prompt_tokens,
            "completion_tokens": state.nebius_completion_tokens,
            "usd": nebius_usd,
            "rate_configured": nebius_priced,
            "key_source": _key_source("NEBIUS_API_KEY", api_keys),
        },
        "amass": {
            "calls": len(amass_calls),
            "live_calls": amass_live,
            "mock_calls": amass_mock,
            "credits_before": state.amass_credits_before,
            "credits_after": state.amass_credits_after,
            "credits_used": credits_used,
            "usd": amass_usd,
            "rate_configured": amass_priced,
            "key_source": _key_source("AMASS_API_KEY", api_keys),
            "note": (
                "credits consumed on this account during the run window "
                "(account-wide balance delta; not isolated to this run if the "
                "API key is shared with other concurrent activity)"
            ),
        },
        "tavily": {
            "calls": len(tavily_calls),
            "live_calls": tavily_live,
            "mock_calls": tavily_mock,
            "usd": tavily_usd,
            "rate_configured": tavily_priced,
            "key_source": _key_source("TAVILY_API_KEY", api_keys),
        },
        "free_tools": free_tools,
        "total_usd": total_usd,
        "total_usd_is_partial": bool(unpriced),
        "unpriced_components": unpriced,
    }
