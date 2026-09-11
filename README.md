# Hypothetically Speaking — a Longevity AI Scientist

An agent that takes a real ageing/longevity research question in plain
English, autonomously plans, retrieves evidence, calls biological data
tools, runs an in-silico gene/pathway enrichment experiment, and returns a
cited, defensible report — hypothesis, what the evidence supports, what it
doesn't, and the next experiment to run — without a human steering each
step.

Built for the "Build a Longevity AI Scientist" hackathon challenge.

## What it does

1. **Plan** — Claude reads the question, proposes 2–4 candidate hypotheses,
   and decides which sources to check for each.
2. **Retrieve** — calls live tools in a loop: literature search, curated
   ageing databases, target–disease evidence, clinical trial status.
3. **Compute** — extracts the gene/protein set implicated by the retrieved
   evidence (via a Nebius-hosted model) and runs a real statistical
   gene/pathway enrichment analysis against it — a computed result, not a
   summary.
4. **Revise** — critiques its own ranking against the combined evidence
   before finalizing.
5. **Report** — a cited markdown report: hypothesis, evidence for/against,
   confidence, stated failure modes, and the next experiment to run, plus a
   full tool-call trace so every claim is traceable.

Target runtime: **under 20 minutes end-to-end**, re-runnable from a clean
checkout in under 30.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.
Short version:

```
frontend/          minimal single-page UI: ask a question, watch the trace, read the report
backend/agent/      the plan -> retrieve -> compute -> revise -> report loop (Anthropic tool-use)
backend/tools/       one wrapper per external tool, each independently toggleable + mockable
backend/server/      FastAPI app: POST /run, SSE stream of trace events, serves the frontend
scripts/             run_demo.py (canonical run + saved transcript), validate_citations.py
docs/                architecture notes, demo script, judge instructions
```

## Tools wired into the loop

| Tool | Purpose | Auth | Live/keyless |
|---|---|---|---|
| Tavily | live web/paper/trial/news retrieval | API key | live |
| Amass | scientific memory: literature, trials, patents, bio data | API key | live |
| Open Targets | target–disease association evidence | none | live, keyless |
| PubMed E-utilities | structured literature search with verifiable PMIDs | none | live, keyless |
| ClinicalTrials.gov API v2 | trial-stage evidence for a target/compound | none | live, keyless |
| GenAge / DrugAge (HAGR) | curated ageing-gene and longevity-compound databases | none | local dataset, downloaded once |
| g:Profiler | gene/pathway enrichment analysis (the in-silico experiment) | none | live, keyless |
| Nebius-hosted model | gene/entity extraction from retrieved abstracts, feeds enrichment | API key | live |

Every tool is individually toggleable via `ENABLED_TOOLS` in `.env` —
disabling one should visibly change the report, proving the tools are
inside the reasoning loop rather than decorative. Every tool also has a
mock/offline fallback so the demo survives a dead key or rate limit.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, TAVILY_API_KEY, AMASS_API_KEY, NEBIUS_API_KEY
python scripts/fetch_datasets.py   # downloads GenAge/DrugAge CSVs once
uvicorn backend.server.app:app --reload
```

Open `http://localhost:8000`, type a longevity question, watch it run.

## Recorded fallback

`scripts/run_demo.py` runs the agent end-to-end on the canonical demo
question and saves the full trace + report under `backend/reports/`, so
there is always a re-playable artifact even if a live API is unavailable
during judging. See [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

## Status

Early scaffold. See `docs/ARCHITECTURE.md` for open TODOs — notably
confirming the exact Amass API/MCP contract and Nebius base URL/model IDs
against the credentials issued at the event.
