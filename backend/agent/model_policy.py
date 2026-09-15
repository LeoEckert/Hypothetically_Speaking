"""Which Claude model a run gets, by deployment environment and tier.

The policy lives in backend/config/models.toml so the dev deployment can be
pinned to Haiku for every tier while production mixes Sonnet and Haiku —
without anyone having to set the right env vars on the right Vercel project.
Precedence for the Anthropic model of a given tier:

1. the user's own pick from the frontend Settings (api_keys["ANTHROPIC_MODEL"]
   for main, api_keys["GROUNDING_FAST_MODEL"] for fast) — only where the
   environment's `allow_override` is true;
2. the environment's section in models.toml;
3. the ANTHROPIC_MODEL / GROUNDING_FAST_MODEL env vars (blank-but-set reads
   as unset, see env.py) — kept for local experiments;
4. the hardcoded defaults below.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from backend.agent.env import env_str

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "models.toml"

DEFAULT_MAIN = "claude-sonnet-5"
DEFAULT_FAST = "claude-haiku-4-5-20251001"
ENVIRONMENTS = ("production", "preview", "development")
OVERRIDE_KEYS = {"main": "ANTHROPIC_MODEL", "fast": "GROUNDING_FAST_MODEL"}


def deployment_env() -> str:
    """APP_ENV wins (local runs, tests), else Vercel's VERCEL_ENV, else development.
    Anything unrecognised is treated as development rather than guessed at."""
    value = env_str("APP_ENV") or env_str("VERCEL_ENV") or "development"
    return value if value in ENVIRONMENTS else "development"


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        with CONFIG_PATH.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        # A missing or broken policy file must never take a run down; the
        # env-var/hardcoded defaults below still apply.
        return {}


def anthropic_policy(environment: str | None = None) -> dict:
    """{"main", "fast", "allow_override", "environment"} for the deployment."""
    environment = environment or deployment_env()
    section = (_load().get(environment) or {}).get("anthropic") or {}
    return {
        "environment": environment,
        "main": section.get("main") or env_str("ANTHROPIC_MODEL", DEFAULT_MAIN),
        "fast": section.get("fast") or env_str("GROUNDING_FAST_MODEL", DEFAULT_FAST),
        "allow_override": bool(section.get("allow_override", True)),
    }


def anthropic_model(tier: str, api_keys: dict | None = None) -> str:
    policy = anthropic_policy()
    tier = tier if tier in OVERRIDE_KEYS else "main"
    override = ((api_keys or {}).get(OVERRIDE_KEYS[tier]) or "").strip()
    if override and policy["allow_override"]:
        return override
    return policy[tier]
