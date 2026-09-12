# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An agent that takes a plain-English ageing/longevity research question and autonomously plans, retrieves evidence, calls biological data tools, runs a real in-silico gene/pathway enrichment analysis, and returns a cited, defensible markdown report. Built for the "Build a Longevity AI Scientist" hackathon challenge; still an early scaffold (see Open TODOs below).

## Commands

```bash
# setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # fill in ANTHROPIC_API_KEY, TAVILY_API_KEY, AMASS_API_KEY, NEBIUS_API_KEY
python scripts/fetch_datasets.py   # one-time download of GenAge/DrugAge CSVs into backend/data/

# run the server + frontend
uvicorn backend.server.app:app --reload    # open http://localhost:8000

# run the agent headlessly on the canonical demo question (or a custom one)
python scripts/run_demo.py ["custom question"]
# saves backend/reports/demo_<run_id>.{json,md} and prints citation coverage

# check citation coverage of a saved run (must be >=95% with no unresolved markers)
python scripts/validate_citations.py backend/reports/<run_id>.json

# tests
python -m pytest tests/                     # all tests
python -m pytest tests/test_tools.py::test_registry_respects_enabled_tools  # single test
```

There is no lint/type-check command configured yet.

## Architecture

```
frontend/           minimal single-page UI: ask a question, watch the trace, read the report
backend/agent/       the plan -> retrieve -> compute -> revise -> report loop (Anthropic tool-use)
backend/tools/       one wrapper per external tool, each independently toggleable + mockable
backend/server/      FastAPI app: POST /api/run, SSE stream of trace events, serves the frontend
scripts/             run_demo.py (canonical run + saved transcript), validate_citations.py, fetch_datasets.py
docs/                ARCHITECTURE.md (full design rationale), DEMO_SCRIPT.md (judge instructions)
```

### The agent loop (`backend/agent/loop.py`)

A **manual** Anthropic Messages API tool-use loop — deliberately not the Claude Agent SDK, so every step is inspectable state rather than framework magic (~200 lines, fully controlled for the "switch a tool off and watch the report change" test). Phases:

1. **PLAN** — Claude states its interpretation/assumptions, proposes 2-4 candidate hypotheses, and picks tools to check each against. Never blocks waiting for clarification.
2. **ACT** — standard tool-use loop: Claude calls tools via the registry, results are appended as `tool_result` blocks and simultaneously registered in the evidence registry under a stable citation ID (e.g. `[PMID:12345678]`, `[OT:ENSG00000142192]`, `[NCT:NCT01234567]`).
3. **COMPUTE** — once evidence names candidate genes/proteins, the agent calls `extract_genes` (Nebius-hosted NER over retrieved abstracts) then `run_enrichment` (g:Profiler) — this is the one required "real computed result, not summarization" step.
4. **REVISE** — a dedicated forced turn: revise the hypothesis ranking against all evidence + the enrichment result, name contradicting evidence, name the next experiment.
5. **REPORT** — final markdown with fixed sections (Hypothesis / Evidence For / Evidence Against / Confidence & Uncertainty / Failure Modes / Next Experiment / Tool Trace); every factual sentence must end in a `[citation-id]` resolvable in the evidence registry.

Run budget is enforced by `RunState` (`backend/agent/state.py`): `MAX_TOOL_CALLS` (default 15) and `MAX_RUN_SECONDS` (default 1080). On budget exhaustion the loop still forces the REPORT phase over whatever evidence exists, marking the run `partial` rather than truncating silently. `on_event(event: dict)` is threaded through the whole loop so callers (the FastAPI SSE endpoint, `scripts/run_demo.py`) can stream/record a run live without touching the loop internals.

### Tool contract (`backend/tools/registry.py`)

Every module under `backend/tools/` exposes exactly:
- `SPEC` — the Claude tool schema (name, description, input_schema)
- `run(args: dict) -> dict` — returns `{"summary": str, "items": [{"id", "url", "summary", "raw"}, ...], "mock": bool, "error": str | None}`

A tool must **never raise** out of `run()` for a missing key / network failure — it degrades to a mock result with the same shape (`registry.run_tool` also catches exceptions defensively as a second line of defense). This mock-fallback contract is what `tests/test_tools.py` checks for every tool, and it's what lets a demo survive a dead API key or an offline sandbox.

`ENABLED_TOOLS` (comma-separated env var, checked via `enabled_tool_names()`) filters which tools are offered to Claude each run — this is the mechanism behind the "turn a tool off, watch the hypothesis ranking and citation mix visibly change" judge test.

### Evidence registry & citation discipline (`backend/agent/state.py`)

`RunState.evidence` maps citation ID -> `EvidenceItem {id, source, url, summary, raw}`. The report prompt requires every claim to carry a matching `[id]`. `scripts/validate_citations.py` parses a saved run's report, extracts every `[id]` marker, and fails if resolved-citation coverage of factual sentences is below 95% or any marker doesn't resolve to a real registry entry — this is the automated version of the "every claim is traceable" bar, and it's run as part of `scripts/run_demo.py`.

### Tools wired into the loop

`tavily` (web/paper/trial search), `amass` (scientific memory), `open_targets` (target-disease evidence, keyless), `pubmed` (E-utilities literature search, keyless), `clinicaltrials` (ClinicalTrials.gov v2, keyless), `genage_drugage` (local HAGR CSVs fetched once via `fetch_datasets.py`, keyless), `run_enrichment` (g:Profiler gene/pathway enrichment, keyless), `extract_genes` (Nebius-hosted NER feeding enrichment).

Note: the registry key and `ENABLED_TOOLS` name for the enrichment tool is `run_enrichment` (must match the tool's `SPEC["name"]`, which is what Claude actually calls) — the module file is still `backend/tools/enrichment_tool.py`. This mismatch (`registry.py` used to key it as `"enrichment"`) previously made the tool silently look "disabled" any time Claude called it; keep the registry key and `SPEC["name"]` in sync for every tool.

## Open TODOs (see `docs/ARCHITECTURE.md` for detail)

- **Amass**: `backend/tools/amass_tool.py` is written against a generic REST/bearer-token shape — the real API/MCP contract isn't confirmed yet.
- **Nebius**: `NEBIUS_BASE_URL` / `NEBIUS_MODEL` are placeholders pending credentials issued at the event.
- If keyless tool calls (PubMed, Open Targets, ClinicalTrials.gov, g:Profiler) get 403s at the CONNECT level, that's very likely a sandboxed dev environment's egress allowlist, not broken tool code — check `docs/ARCHITECTURE.md`'s note on this before debugging further. These tools should work live with no code changes outside such a sandbox.
