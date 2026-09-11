# Demo script (for judges)

## Live run (target: under 30 minutes from a clean checkout)

```bash
git clone <repo> && cd Hypothetically_Speaking
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in ANTHROPIC_API_KEY, TAVILY_API_KEY, AMASS_API_KEY, NEBIUS_API_KEY in .env
python scripts/fetch_datasets.py      # one-time GenAge/DrugAge download
uvicorn backend.server.app:app --reload
```

Open `http://localhost:8000`. Type a longevity/ageing research question
(e.g. *"Does activating SIRT1 plausibly extend human healthspan via
improved mitochondrial biogenesis?"*), click **Run**, and watch the trace
panel: PLAN → tool calls (with mock/live tagging) → REVISE → the cited
report. Target end-to-end runtime is under 20 minutes.

## "Switch a tool off" test

Edit `.env`, remove one tool from `ENABLED_TOOLS` (e.g. drop `open_targets`),
restart the server, and re-run the same question. The evidence mix and the
citation set in the final report should visibly change — that's the proof
the tools are inside the reasoning loop, not decorative.

## CLI / recorded fallback

```bash
python scripts/run_demo.py "Does activating SIRT1 plausibly extend human healthspan via improved mitochondrial biogenesis?"
```

This runs the same loop headlessly, prints the live trace to the
terminal, and saves a full transcript + report under
`backend/reports/demo_<run_id>.{json,md}`. If live APIs are unavailable at
judging time (venue wifi, a dead key, a rate limit), this saved transcript
is the fallback artifact — open the `.md` report directly, or re-run
`python scripts/validate_citations.py backend/reports/demo_<run_id>.json`
to show the citation-coverage check passing against the saved run.

## Citation coverage check

```bash
python scripts/validate_citations.py backend/reports/demo_<run_id>.json
```

Prints the fraction of factual sentences carrying a citation marker and
flags any marker that doesn't resolve to a real evidence-registry entry.
Exits 0 (PASS) only when coverage is ≥95% and every citation resolves.
