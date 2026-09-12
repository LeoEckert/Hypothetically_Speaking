"""Nebius-hosted open model: gene/protein entity extraction from retrieved text.

This is the Nebius integration point in the loop: instead of Claude itself
parsing gene symbols out of abstracts, a Nebius-hosted open model (via its
OpenAI-compatible Token Factory endpoint) does the NER pass. The resulting
gene list feeds directly into run_enrichment — a real subtask handed off to
the partner-provided compute, not a decorative call.
"""
from __future__ import annotations

import json
import os
import re

from openai import OpenAI

SPEC = {
    "name": "extract_genes",
    "description": (
        "Extract human gene/protein symbols mentioned in a block of retrieved "
        "text (abstracts, summaries) using a Nebius-hosted model. Call this "
        "after gathering literature/database evidence, before run_enrichment, "
        "to build a clean gene list from the free text you've collected."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "concatenated evidence summaries to extract genes from"},
        },
        "required": ["text"],
    },
}

_GENE_SYMBOL_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
_COMMON_FALSE_POSITIVES = {"DNA", "RNA", "USA", "PMID", "NCT", "API", "HTTP"}


def _heuristic_fallback(text: str) -> list[str]:
    candidates = {m.group(0) for m in _GENE_SYMBOL_RE.finditer(text)}
    return sorted(candidates - _COMMON_FALSE_POSITIVES)[:15]


def run(args: dict) -> dict:
    text = args["text"]
    api_key = os.environ.get("NEBIUS_API_KEY")
    base_url = os.environ.get("NEBIUS_BASE_URL")
    model = os.environ.get("NEBIUS_MODEL", "meta-llama/Meta-Llama-3.1-70B-Instruct")

    if not api_key or not base_url:
        genes = _heuristic_fallback(text)
        return {
            "summary": (
                "Nebius not configured (NEBIUS_API_KEY/NEBIUS_BASE_URL missing); "
                f"used a regex heuristic instead. Candidate genes: {genes}"
            ),
            "items": [],
            "mock": True,
            "error": "missing_config",
            "genes": genes,
        }

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract every human gene or protein symbol mentioned in the "
                        "given text (e.g. SIRT1, FOXO3, MTOR, APOE). Respond with ONLY "
                        'a JSON array of unique uppercase symbols, e.g. ["SIRT1","FOXO3"]. '
                        "If none are found, respond with []."
                    ),
                },
                {"role": "user", "content": text[:8000]},
            ],
            temperature=0,
        )
        content = resp.choices[0].message.content.strip()
        match = re.search(r"\[.*\]", content, re.DOTALL)
        genes = json.loads(match.group(0)) if match else []
        genes = sorted({g.strip().upper() for g in genes if g.strip()})
    except Exception as exc:
        genes = _heuristic_fallback(text)
        return {
            "summary": f"Nebius extraction failed ({exc}); used a regex heuristic. Candidate genes: {genes}",
            "items": [],
            "mock": True,
            "error": str(exc),
            "genes": genes,
        }

    return {
        "summary": f"Extracted candidate gene/protein symbols via Nebius-hosted {model}: {genes}",
        "items": [],
        "mock": False,
        "error": None,
        "genes": genes,
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
        },
    }
