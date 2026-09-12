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

The web UI (Vite + React + shadcn/ui) also shows, live: which tools were
called and whether each call was live or mock, a running cost/usage
breakdown per provider (Anthropic, Nebius, Amass, Tavily — real numbers
only, never a guessed dollar figure), a `localStorage`-backed history of
past runs you can revisit or fork into a new question, and per-tool
enable/disable switches.

Target runtime: **under 20 minutes end-to-end**, re-runnable from a clean
checkout in under 30.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.
Short version:

```
frontend/          Vite + React + shadcn/ui SPA: ask a question, watch the trace, read the report, browse history
backend/agent/      the plan -> retrieve -> compute -> revise -> report loop (Anthropic tool-use)
backend/tools/       one wrapper per external tool, each independently toggleable + mockable
backend/server/      FastAPI app: POST /api/run, SSE stream of trace events, tool toggle + cost/usage endpoints
scripts/             run_demo.py (canonical run + saved transcript), validate_citations.py
docs/                architecture notes, deploy guide, demo script, judge instructions
```

`frontend/` and `backend/` are deployed separately (see `docs/DEPLOY.md`) —
the frontend is a static build (Vercel-friendly), the backend is a standalone
API the frontend talks to cross-origin. Locally, run both at once (see Setup
below).

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

Every tool is individually toggleable — via `ENABLED_TOOLS` in `.env`, or
live from the web UI's "Available tools" switches (applies starting with
the *next* run, never an in-flight one). Disabling one should visibly
change the report, proving the tools are inside the reasoning loop rather
than decorative. Every tool also has a mock/offline fallback so the demo
survives a dead key or rate limit.

## Setup

```bash
# backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, TAVILY_API_KEY, AMASS_API_KEY, NEBIUS_API_KEY
python scripts/fetch_datasets.py   # downloads GenAge/DrugAge CSVs once
uvicorn backend.server.app:app --reload   # http://localhost:8000 (API only)

# frontend (separate terminal)
cd frontend
npm install
npm run dev   # http://localhost:5173 — talks to the backend above by default
```

Open `http://localhost:5173`, type a longevity question, watch it run.

**This local setup is fully self-contained** — it never talks to Vercel or
Nebius. The frontend's backend URL (`VITE_API_BASE_URL`) only matters for a
deployed build; in `vite dev` it always falls back to
`http://localhost:8000`. For deploying the frontend on Vercel and the
backend on a Nebius VM instead, see `docs/DEPLOY.md`.

## Recorded fallback

`scripts/run_demo.py` runs the agent end-to-end on the canonical demo
question and saves the full trace + report under `backend/reports/`, so
there is always a re-playable artifact even if a live API is unavailable
during judging. See [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

## Status

Deployed: frontend on Vercel, backend on a Nebius VM (see `docs/DEPLOY.md`
for the current URLs and the full setup). See `docs/ARCHITECTURE.md` for
open TODOs — notably that `NEBIUS_API_KEY` has never been set, so
`extract_genes` still runs on its regex-heuristic fallback rather than the
real Nebius-hosted NER model (the Amass contract is confirmed and live).
