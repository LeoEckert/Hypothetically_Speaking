# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An agent that takes a plain-English ageing/longevity research question and autonomously plans, retrieves evidence, calls biological data tools, runs a real in-silico gene/pathway enrichment analysis, and returns a cited, defensible markdown report. Built for the "Build a Longevity AI Scientist" hackathon challenge. Deployed: frontend on Vercel, backend on a Nebius VM — see `docs/DEPLOY.md`.

## Commands

```bash
# backend setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # fill in ANTHROPIC_API_KEY, TAVILY_API_KEY, AMASS_API_KEY, NEBIUS_API_KEY
python scripts/fetch_datasets.py   # one-time download of GenAge/DrugAge CSVs into backend/data/

# run the backend (API only — no frontend serving)
uvicorn backend.server.app:app --reload    # http://localhost:8000

# frontend, separate terminal — fully independent of any cloud deployment;
# VITE_API_BASE_URL falls back to http://localhost:8000 in `vite dev`
cd frontend && npm install && npm run dev  # http://localhost:5173

# run the agent headlessly on the canonical demo question (or a custom one)
python scripts/run_demo.py ["custom question"]
# saves backend/reports/demo_<run_id>.{json,md} and prints citation coverage

# check citation coverage of a saved run (must be >=95% with no unresolved markers)
python scripts/validate_citations.py backend/reports/<run_id>.json

# tests
python -m pytest tests/                     # all tests
python -m pytest tests/test_tools.py::test_registry_respects_enabled_tools  # single test

# frontend build/lint
cd frontend && npm run build   # tsc -b && vite build
cd frontend && npm run lint    # oxlint
```

There is no Python lint/type-check command configured.

## Architecture

```
frontend/            Vite + React + TS + shadcn/ui SPA — a separately-deployed static build with no server code
backend/agent/        the plan -> retrieve -> compute -> revise -> report loop (Anthropic tool-use), plus cost/usage accounting
backend/tools/         one wrapper per external tool, each independently toggleable + mockable
backend/server/        FastAPI app: POST /api/run, SSE stream of trace events, tool toggle + config/tools endpoints
scripts/               run_demo.py (canonical run + saved transcript), validate_citations.py, fetch_datasets.py
docs/                  ARCHITECTURE.md (design + diagram), DEPLOY.md (Vercel/Nebius setup), DEMO_SCRIPT.md
Dockerfile, docker-compose.yml, Caddyfile, vercel.json   deployment config (see docs/DEPLOY.md)
```

`frontend/` and `backend/` are deployed and run **completely independently** — the frontend is a static build with zero server-side code, the backend is a plain JSON/SSE API with no knowledge of who's calling it (CORS-gated). Locally this is two terminals (`uvicorn` + `vite dev`) talking over `localhost`; in production it's Vercel (static) talking cross-origin to a Nebius VM. See `docs/ARCHITECTURE.md`'s System diagram.

### The agent loop (`backend/agent/loop.py`)

A **manual** Anthropic Messages API tool-use loop — deliberately not the Claude Agent SDK, so every step is inspectable state rather than framework magic. Phases:

1. **PLAN** — Claude states its interpretation/assumptions, proposes 2-4 candidate hypotheses, and picks tools to check each against. Never blocks waiting for clarification.
2. **ACT** — standard tool-use loop: Claude calls tools via the registry (using a run-start snapshot of enabled tools, see below), results are appended as `tool_result` blocks and simultaneously registered in the evidence registry under a stable citation ID (e.g. `[PMID:12345678]`, `[OT:ENSG00000142192]`, `[NCT:NCT01234567]`).
3. **COMPUTE** — once evidence names candidate genes/proteins, the agent calls `extract_genes` (Nebius-hosted NER over retrieved abstracts, or a regex heuristic fallback since `NEBIUS_API_KEY` isn't set) then `run_enrichment` (g:Profiler) — this is the one required "real computed result, not summarization" step.
4. **REVISE** — a dedicated forced turn: revise the hypothesis ranking against all evidence + the enrichment result, name contradicting evidence, name the next experiment.
5. **REPORT** — final markdown with fixed sections (Hypothesis / Evidence For / Evidence Against / Confidence & Uncertainty / Failure Modes / Next Experiment / Tool Trace); every factual sentence must end in a `[citation-id]` resolvable in the evidence registry.

Run budget is enforced by `RunState` (`backend/agent/state.py`): `MAX_TOOL_CALLS` (default 30 — raised from an initial 15 after real runs on thorough questions were consistently hitting that ceiling and getting cut off `partial`) and `MAX_RUN_SECONDS` (default 1080). On budget exhaustion the loop still forces the REPORT phase over whatever evidence exists, marking the run `partial` rather than truncating silently. `on_event(event: dict)` is threaded through the whole loop so callers (the FastAPI SSE endpoint, `scripts/run_demo.py`) can stream/record a run live without touching the loop internals.

A known, previously-reproduced bug (fixed): Claude occasionally returns a text content block with empty/whitespace-only text alongside a tool_use or thinking block; resending that verbatim on the next turn gets a 400 ("text content blocks must be non-empty") and aborted the whole run. `loop.py`'s `_strip_empty_text_blocks()` filters these out before any assistant turn gets re-appended to `messages`.

### Tool contract (`backend/tools/registry.py`)

Every module under `backend/tools/` exposes:
- `SPEC` — the Claude tool schema (name, description, input_schema)
- `run(args: dict) -> dict` — returns `{"summary": str, "items": [{"id", "url", "summary", "raw"}, ...], "mock": bool, "error": str | None}`, plus an optional extra `usage: {"prompt_tokens", "completion_tokens"}` key (currently only `extract_genes`, for Nebius cost accounting)

A tool must **never raise** out of `run()` for a missing key / network failure — it degrades to a mock result with the same shape (`registry.run_tool` also catches exceptions defensively as a second line of defense). This mock-fallback contract is what `tests/test_tools.py` checks for every tool.

`ENABLED_TOOLS` (comma-separated env var) sets the default; `registry.set_tool_enabled(name, bool)` — exposed via `PUT /api/tools/{name}` and driven by the frontend's per-tool switches — layers a runtime-only override on top (resets on process restart). `run_tool(name, args, enabled_names=...)` takes an explicit set so a run's tool availability is **snapshotted once at run start** (`state.enabled_tools`) — toggling a tool mid-run never affects that in-flight run, only the next one.

### Cost/usage tracking (`backend/agent/costs.py`)

Every run accumulates real Anthropic token counts, Nebius token counts, Amass account credit balance (sampled before/after via `amass_tool.get_credits()`), and Tavily/free-tool call counts, then `build_cost_summary()` turns that into a per-provider breakdown on the `done` SSE event and the saved report JSON. Rule: **never show a `$` figure without a configured rate** — Anthropic has a hardcoded (drifts, re-verify) price table; Nebius/Amass/Tavily need `NEBIUS_PRICE_PER_1M_INPUT`/`_OUTPUT`, `AMASS_PRICE_PER_CREDIT`, `TAVILY_USD_PER_CALL` set or their `usd` stays `null` with `rate_configured: false`.

### Evidence registry & citation discipline (`backend/agent/state.py`)

`RunState.evidence` maps citation ID -> `EvidenceItem {id, source, url, summary, raw}`. The report prompt requires every claim to carry a matching `[id]`. `scripts/validate_citations.py` parses a saved run's report, extracts every `[id]` marker, and fails if resolved-citation coverage of factual sentences is below 95% or any marker doesn't resolve to a real registry entry.

### Backend API (`backend/server/app.py`)

`GET /api/config` (dev-mode demo question), `GET /api/tools` / `PUT /api/tools/{name}` (roster + toggle), `POST /api/run` (starts a background thread, returns `run_id`), `GET /api/run/{run_id}/stream` (SSE — replays everything so far from an in-memory per-run event list before tailing live, so a reload or a late "view live run" attach never misses or double-delivers events), `GET /api/run/{run_id}/result`. CORS via `ALLOWED_ORIGINS` (exact list) + `ALLOWED_ORIGIN_REGEX` (default matches any `*.vercel.app`, since Vercel preview deployments get a fresh hostname per branch). All state (`_run_events`, `_results`) is in-memory — a restart mid-run loses it (pre-existing, undocumented-as-a-problem limitation).

### Frontend (`frontend/`)

Vite + React + TypeScript + shadcn/ui. `src/store/runsStore.ts` is a vanilla subscribe/getSnapshot store (via `useSyncExternalStore`) backing a `localStorage`-persisted run history — every SSE event for every run gets appended there live. `src/lib/runStream.ts` holds a module-level `EventSource` singleton keyed by `run_id`, created exactly once per run (avoids React StrictMode double-subscription against the backend's single-reader-friendly-but-not-required-multi-reader SSE design). Components: `Sidebar`/`HistoryList`/`ToolsPanel`/`HowItWorksPanel`, `ComposeBox`, `TraceTimeline`/`ToolStepCard`/`ReasoningBlock`/`ErrorBanner`, `ReportView` (resolves `[citation-id]` markers against the `done` event's evidence map), `CostPanel`.

### Tools wired into the loop

`tavily` (web/paper/trial search), `amass` (Amass Cores API — biomedcore/trialcore/drugcore/patentcore/genecore/regulatorycore, confirmed contract), `open_targets` (keyless), `pubmed` (E-utilities, keyless), `clinicaltrials` (ClinicalTrials.gov v2, keyless), `genage_drugage` (local HAGR CSVs fetched once via `fetch_datasets.py`, keyless), `run_enrichment` (g:Profiler, keyless), `extract_genes` (Nebius-hosted NER, currently regex-heuristic fallback — no key set).

Note: the registry key and `ENABLED_TOOLS` name for the enrichment tool is `run_enrichment` (must match the tool's `SPEC["name"]`, which is what Claude actually calls) — the module file is still `backend/tools/enrichment_tool.py`. Keep the registry key and `SPEC["name"]` in sync for every tool, or the tool silently looks "disabled" whenever Claude calls it.

## Open TODOs

- **Nebius**: `NEBIUS_API_KEY` has never been set — `extract_genes` runs on its regex fallback. Set the three `NEBIUS_*` env vars once real credentials exist.
- **Amass**: `drugcore`/`genecore`/`regulatorycore` record-to-citation mapping in `amass_tool.py` falls back to a generic name-like-field guess (their schemas weren't in the fetched OpenAPI spec) — `biomedcore`/`trialcore`/`patentcore` are mapped from confirmed schemas.
- **Deployment**: see `docs/DEPLOY.md` for the current live URLs and known gotchas (region-scoped image/platform IDs, vCPU quota per region, the Vercel MCP tooling bug that made a dashboard import the reliable path instead of API-driven project creation).
