"""Wires the live adapters together for a real grounding run — L0-L4 with
BYOK providers and either Amass or (keyless) PubMed/ClinicalTrials.gov
sources, depending on what's configured.

This lives inside the importable `backend` package rather than `scripts/`
on purpose: `scripts/` is a CLI-only directory that never ships to
production (`.github/workflows/deploy-frontend.yml`'s staging step copies
only `backend/` into the deployed Vercel function). `ground()` used to live
in `scripts/run_grounding.py`, which worked in every environment tested
locally — but broke the first time it actually ran in production
(`ModuleNotFoundError: No module named 'scripts'`), because grounding used
to always short-circuit earlier on a missing AMASS_API_KEY before ever
reaching this import; once that requirement was removed, this import was
the very next thing hit. `scripts/run_grounding.py` still re-exports
`ground` for its own CLI use (`--premises`); its CLI-only concerns
(`output()`, `archive()`, `live()`, `replay()`, `main()`) stay there, since
none of those are ever imported at runtime.
"""

from __future__ import annotations

import os

from backend.grounding import premises
from backend.grounding.adapters import (
    ABSTRACT_CHARS,
    ABSTRACT_CHARS_FAST,
    AMASS_LIMIT,
    TRIAL_LIMIT_FAST,
    AmassPaperRepository,
    AmassTrialRepository,
    ClaudeHypothesisGenerator,
    ClaudeProber,
    ClaudeTriplifier,
    ClaudeVerifier,
    ClinicalTrialsRepository,
    PubMedPaperRepository,
)
from backend.grounding.knowledge_base import SqliteKnowledgeBase


def ground(
    question: str, ledger=None, fast: bool = False, on_progress=None, api_keys: dict | None = None
) -> premises.Grounding:
    """L0-L4 with live adapters; the knowledge base caches every LLM call and
    literature-source query. `ledger` (adapters.Ledger) receives every
    external call. `api_keys` (env-var-name -> value) is a per-request BYOK
    override — an Anthropic key selects Claude via
    backend.agent.providers.get_provider(); otherwise an OpenRouter key is
    used, same as the main agent loop. One of the two is required — there's
    no platform-held key for either.

    Amass (curated, single-call) is used when an AMASS_API_KEY is
    configured (BYOK or platform); otherwise the keyless
    PubMedPaperRepository/ClinicalTrialsRepository pair stands in — Amass
    has no free tier, so grounding must not require one.

    L0, L2 verdicts and L4 stay on the "main" tier in both modes (see the note
    on Haiku verdicts in adapters.py); L1 probing runs on the "fast" tier.
    normal: 8 links, whole abstracts, 20 trials per query, a second-look search
            before a link is called unverified.
    fast:   4 links, 1500-char abstracts, 10 trials per query, no second look."""
    from backend.agent.providers import get_provider

    knowledge_base = SqliteKnowledgeBase()
    main_provider = get_provider(api_keys, tier="main")
    fast_provider = get_provider(api_keys, tier="fast")
    amass_key = (api_keys or {}).get("AMASS_API_KEY") or os.environ.get("AMASS_API_KEY")
    sources = (
        [
            AmassPaperRepository(knowledge_base, ledger, amass_key),
            AmassTrialRepository(knowledge_base, ledger, TRIAL_LIMIT_FAST if fast else AMASS_LIMIT, amass_key),
        ]
        if amass_key
        else [
            PubMedPaperRepository(TRIAL_LIMIT_FAST if fast else AMASS_LIMIT),
            ClinicalTrialsRepository(TRIAL_LIMIT_FAST if fast else AMASS_LIMIT),
        ]
    )
    return premises.extract(
        question,
        triplifier=ClaudeTriplifier(knowledge_base, ledger, main_provider),
        prober=ClaudeProber(knowledge_base, ledger, fast_provider),
        sources=sources,
        verifier=ClaudeVerifier(knowledge_base, ledger, main_provider, ABSTRACT_CHARS_FAST if fast else ABSTRACT_CHARS),
        # The seam: swap in any object with generate(grounding) -> list[Hypothesis].
        generator=ClaudeHypothesisGenerator(knowledge_base, ledger, main_provider),
        knowledge_base=knowledge_base,
        fast=fast,
        on_progress=on_progress,
    )
