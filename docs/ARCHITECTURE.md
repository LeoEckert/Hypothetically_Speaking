# Architecture

## Goals this design is optimized for

1. Agent plans, retrieves, calls tools, and revises without hand-holding.
2. At least one real biological/data tool call inside the reasoning loop —
   the enrichment analysis is a computed result, not a text summary.
3. A cited final report a clinician or investor can read in one pass.
4. Stated uncertainty and failure modes as a first-class report section.
5. A demo a judge can re-run from a clean checkout in under 30 minutes,
   plus a recorded fallback artifact.

## Agent loop (`backend/agent/loop.py`)

Implemented as a manual Anthropic Messages API tool-use loop (not the
Claude Agent SDK) — chosen for transparency and low dependency risk within
a 36-hour build: every step is inspectable state, not framework magic, and
the whole loop is ~200 lines we fully control for the judge's "switch a
tool off and watch it change" test.

```
1. PLAN     Claude reads the question, states its interpretation/assumptions
            explicitly (never blocks waiting for clarification), proposes
            2-4 candidate hypotheses, and picks which tools to check each
            against.
2. ACT      Standard tool-use loop: Claude calls tools, we execute them via
            the registry, append tool_result blocks, repeat. Every tool
            result is stored in the evidence registry with a stable
            citation ID (e.g. [PMID:12345678], [OT:ENSG00000142192],
            [NCT:NCT01234567], [S3] for a Tavily/Amass hit).
3. COMPUTE  Once literature/DB evidence names candidate genes/proteins, the
            agent calls extract_genes (Nebius-hosted model NER over the
            retrieved abstracts) to build a gene list, then calls
            run_enrichment (g:Profiler) against it. This is the required
            "real tool call, not just summarization" step producing an
            actual statistical result (adjusted p-values per pathway).
4. REVISE   A dedicated turn: "given all evidence and the enrichment
            result, revise your hypothesis ranking; name the best-
            supported hypothesis, name contradicting evidence, and specify
            the next experiment." This is where the agent is forced to
            weigh evidence rather than just concatenate it.
5. REPORT   Final markdown: Hypothesis / Evidence For / Evidence Against /
            Confidence & Uncertainty / Failure Modes / Next Experiment /
            Tool Trace. Every factual sentence must carry an inline
            citation ID resolvable in the evidence registry.
```

Budget enforcement: `MAX_TOOL_CALLS` (default 15) and a wall-clock
timeout (default 18 min) in `state.py`. On timeout the loop still forces a
REPORT pass over whatever evidence exists, flagged as a partial run —
never silently truncates without saying so.

## Evidence registry & citation discipline (`backend/agent/state.py`)

Every tool result is appended to `RunState.evidence` as:

```python
{"id": "PMID:12345678", "source": "pubmed", "url": "...", "summary": "...", "raw": {...}}
```

The report-writing prompt requires every claim to end in `[id]` matching a
registry entry. `scripts/validate_citations.py` parses a finished report,
extracts every `[id]` marker, and checks each resolves to a registry entry
with a working URL — this is the automated check behind the "95% of
claims carry a working citation" bar, run as part of `run_demo.py`.

## Tool registry (`backend/tools/registry.py`)

Each tool module exposes:

- `SPEC` — the Claude tool schema (name, description, input schema)
- `run(args: dict) -> dict` — executes the call; on missing API key or
  network failure, returns `{"mock": true, "error": "...", ...}` with
  representative sample shape so the loop degrades gracefully rather than
  crashing.

`ENABLED_TOOLS` (env var, comma-separated tool names) filters which `SPEC`s
are offered to Claude each run. This is the mechanism behind the judge
"turn a tool off" test: remove `open_targets` from the list and re-run —
the hypothesis ranking and citation mix visibly change because that
evidence is no longer available to reason over.

## Open TODOs / confirm at the event

- **Amass**: contract confirmed 2026-09-12 against
  `https://api.amass.tech/api/doc/openapi.json`. It's `GET
  {AMASS_API_URL}/cores/{core}/records?query=...&limit=...` with
  `Authorization: Bearer <AMASS_API_KEY>`, one endpoint per Core
  (biomedcore/trialcore/drugcore/patentcore/genecore/regulatorycore).
  `backend/tools/amass_tool.py` maps `biomedcore`, `trialcore`, and
  `patentcore` records to citations from their confirmed schemas;
  `drugcore`/`genecore`/`regulatorycore` fall back to a generic
  name-like-field guess since their record schemas weren't in the fetched
  OpenAPI spec — tighten that mapping if/when those fields are confirmed.
- **Nebius**: base URL and model ID for the hosted NER subtask are
  env-configured (`NEBIUS_BASE_URL`, `NEBIUS_MODEL`) — confirm against the
  Token Factory credentials issued at the venue.
- **GenAge/DrugAge**: HAGR does not expose a live query API; datasets are
  downloaded once via `scripts/fetch_datasets.py` from
  https://genomics.senescence.info/download and queried locally.

## A note on this dev sandbox

This scaffold was built inside a network-restricted Claude Code sandbox
whose egress policy denies arbitrary outbound hosts (confirmed via
`/root/.ccr/__agentproxy/status`: `eutils.ncbi.nlm.nih.gov`,
`api.platform.opentargets.org`, `clinicaltrials.gov`, and `biit.cs.ut.ee`
were all rejected with 403 at the CONNECT level — a policy denial, not a
bug). Every keyless tool (PubMed, Open Targets, ClinicalTrials.gov,
g:Profiler) was verified to degrade to its mock fallback correctly rather
than crash when this happens — see `tests/test_tools.py`. On an
unrestricted machine (a laptop, the hackathon venue's environment, or a
sandbox with a broader allowlist) these calls should work live with no
code changes. If you see the same 403 pattern elsewhere, check that
sandbox's egress allowlist rather than assuming the tool code is broken.

## Stretch goals (explicitly out of MVP scope)

- ElevenLabs voice briefing of the final report.
- Lovable-built polished frontend (current frontend is a deliberately
  minimal hand-built page so the core loop ships first).
