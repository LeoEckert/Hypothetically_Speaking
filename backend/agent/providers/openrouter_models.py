"""Runtime discovery of OpenRouter's free-tier models.

Nothing here is a hardcoded model slug. OpenRouter adds and retires `:free`
models on its own schedule (the roster has churned repeatedly over the life
of this project) — pinning today's best pick as a constant would silently go
stale, or worse, silently start routing to a model that lost its free
variant. Instead this asks OpenRouter's own public catalog, every time a
provider is constructed (subject to the cache below), which model is
currently free and can do tool calling, and ranks whatever comes back.
"""

from __future__ import annotations

import time

import httpx

_MODELS_URL = "https://openrouter.ai/api/v1/models"
_TTL_SECONDS = 3600  # a warm serverless instance reuses this across requests; a cold one just refetches once
_FETCH_TIMEOUT = 5.0  # never let a slow catalog fetch eat into the 300s run budget

_cache: dict = {"models": None, "fetched_at": 0.0}

# Absolute last resort, only reached if OpenRouter's catalog is unreachable
# and no cache exists yet — not a "best" pick, just something that has always
# existed and keeps a run from hard-failing during a transient outage.
_FALLBACK_MODEL = "openrouter/auto"


def _fetch_models() -> list[dict]:
    now = time.monotonic()
    if _cache["models"] is not None and (now - _cache["fetched_at"]) < _TTL_SECONDS:
        return _cache["models"]
    try:
        response = httpx.get(_MODELS_URL, timeout=_FETCH_TIMEOUT)
        response.raise_for_status()
        models = response.json().get("data", [])
    except Exception:
        # Serve a stale cache over a hard failure if one exists; the caller
        # falls back to _FALLBACK_MODEL only when there's truly nothing.
        return _cache["models"] or []
    _cache["models"] = models
    _cache["fetched_at"] = now
    return models


def _score(model: dict) -> tuple[float, float, float, int]:
    """Highest tuple wins. Agentic performance is the most relevant single
    number for a tool-calling loop; intelligence/coding are reasonable
    tie-breakers for the free models that don't have an agentic score yet;
    context length is a last-resort tiebreaker so the ranking is total even
    with zero benchmark data."""
    bench = (model.get("benchmarks") or {}).get("artificial_analysis") or {}

    def _or_min(value: float | None) -> float:
        return value if value is not None else -1.0

    return (
        _or_min(bench.get("agentic_index")),
        _or_min(bench.get("intelligence_index")),
        _or_min(bench.get("coding_index")),
        model.get("context_length") or 0,
    )


def _free_tool_candidates() -> list[dict]:
    return [
        model
        for model in _fetch_models()
        if model.get("id", "").endswith(":free") and "tools" in (model.get("supported_parameters") or [])
    ]


def list_free_tool_models() -> list[dict]:
    """Every currently-free, tool-calling-capable OpenRouter model, best
    first — the same filter+ranking `best_free_tool_model()` uses, exposed
    for callers that want the whole list (e.g. GET /api/models) rather than
    just the top pick. Each entry: {"id", "name", "context_length"}."""
    candidates = sorted(_free_tool_candidates(), key=_score, reverse=True)
    return [
        {"id": model["id"], "name": model.get("name", model["id"]), "context_length": model.get("context_length")}
        for model in candidates
    ]


def best_free_tool_model() -> str:
    """The single best currently-free, tool-calling-capable OpenRouter model,
    picked live from OpenRouter's own catalog. Never a hardcoded slug."""
    candidates = _free_tool_candidates()
    if not candidates:
        return _FALLBACK_MODEL
    return max(candidates, key=_score)["id"]
