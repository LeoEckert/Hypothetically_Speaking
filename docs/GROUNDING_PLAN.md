# Grounding extractor: question → premises + knowledge graph

## Where things landed

Moved out of the `ai-scientist` repo (archived there on branch
`spike/ai-scientist-kb`) into this one:

| Here | Was |
|---|---|
| `backend/grounding/{domain,knowledge_base,stages,adapters}.py` | `backend/grounding/` |
| `scripts/run_grounding.py` | `script.py` (CLI only; selftest split out) |
| `tests/test_grounding.py` | `script.py::selftest`, now pytest |
| `docs/reference/` | hackathon brief + longevity run report |

Environment: conda env `hypspeak` (arm64, py3.12) — the old `.venv` was an
x86_64 build under Rosetta and `uv` could not resolve `torch` for it.

```bash
~/miniforge3/envs/hypspeak/bin/python -m pytest -q
```

## Context

The deliverable is now precisely specified by
`~/Documents/Private/Hypothetically_Speaking/docs/GROUNDING_INTEGRATION.md`:

```
question: str → unverified_premises, knowledge_graph → plan_prompt(premises, graph)
```

Hook point: `backend/agent/loop.py::run_agent`, after the first `_emit`, before
the PLAN block. Persist on `RunState.unverified_premises` / `.knowledge_graph`.
**We stop at premises.** The next team generates hypotheses from them using SPOKE.

The user's reasoning chain, which is the thing to build:

```
question (free form)
  │
  L0  Is this even a coherent scientific question?          Claude
      Decompose into A -verb-> B triples, nothing embellished
  │
  L1  Naive hypotheses from the triples alone — no external  Claude
      knowledge. These are PROBES, not output.
  │
  L2  Activate the knowledge repository: has each probe      SPOKE + Amass
      already been verified elsewhere, and how?
  │
  L3  From what similar papers verify or merely mention,     Claude + KB
      synthesise premises for new testable hypotheses
  ▼
  unverified_premises + knowledge_graph
```

L1 exists to give L2 something specific to look up. Generating naive hypotheses
first and then checking them is what makes "already verified, and how" answerable
— you cannot query a knowledge base for the absence of something you have not
articulated.

## Worked example — the reference case for the whole design

> *"Does activating SIRT1 plausibly extend human healthspan via improved
> mitochondrial biogenesis, and what is the strongest next experiment to test
> that mechanism?"*

**L0 — coherence, then triples.** The question is coherent: a named intervention,
a named mechanism, a named outcome. It carries two asks, and only the first is a
premise problem — the experiment request is the downstream deliverable, so L0
must split them rather than triplify "what is the strongest next experiment".

The word **"via" is what creates a chain**: `A extends C via B` is not one claim
but two links.

```
SIRT1 activation ──extends──▶ human healthspan        (the overall claim)
        │                              ▲
        └──improves──▶ mitochondrial ──┘
                        biogenesis
```

**L1 — probes elaborate the chain, using no external knowledge.** Claude inserts
the mechanistic intermediaries a biologist would expect, turning `A→B→C` into
something specific enough to look up:

```
SIRT1 ──deacetylates──▶ PGC-1α ──triggers──▶ mitochondrial biogenesis
   ──improves──▶ respiratory capacity ──?──▶ human healthspan
```

**L2 — activation, link by link.** Each link is checked separately against SPOKE
and Amass. The verdicts are not uniform, and that is the entire point:

| Link | Verdict |
|---|---|
| SIRT1 → deacetylates → PGC-1α | **ESTABLISHED** — dense literature |
| PGC-1α → triggers → mitochondrial biogenesis | **ESTABLISHED** |
| SIRT1 activation → extends → human healthspan | **CONTESTED** — resveratrol/NAD⁺ trials conflict |
| mitochondrial biogenesis → extends → human healthspan | **UNVERIFIED** — graph path exists, direct human evidence absent |

**L3 — the weakest link is the answer.** The chain is solid at the molecular end
and unverified at the organismal end. `unverified_premises` carries the last two
rows, and that is precisely what the next team should aim a hypothesis at.

This closes the question's second ask for free: **the strongest next experiment is
the one that tests the weakest link.** We never generate the experiment — we
identify which link is load-bearing and unsupported, and hand that over.

**Correction to my earlier read.** Last turn I concluded the grounding spike
should be dropped in favour of upstream. That was wrong on one point: the user
has since clarified the graph is *"knowledge repository/cache layer, per session
or per project"*, not a from-scratch grounding KB. That is exactly what
`backend/grounding/knowledge_base.py` is. The KB survives; the Tavily/Amass adapters
and the MeSH co-occurrence gap SQL still do not.

## Decisions (confirmed)

| Question | Decision |
|---|---|
| Premise shape | Triple **and** rendered statement — struct is canonical, sentence derived |
| Delivery | ~~Single file copied~~ — superseded: we now work inside this repo, so `backend/grounding/` is a normal package |

Single-file with zero new dependencies is achievable: that repo already uses
`from anthropic import Anthropic` directly (`backend/agent/loop.py:15`), already
has `httpx`, and already ships `backend/tools/amass_tool.py`. `sqlite3` is stdlib.
**Use the raw `anthropic` SDK, not langchain** — matching the consumer's style.

## The premise schema

```json
{
  "subject": "mitochondrial biogenesis",
  "verb": "extends",
  "object": "human healthspan",
  "statement": "Increased mitochondrial biogenesis extends human healthspan",
  "status": "UNVERIFIED",
  "evidence": [],
  "absence_checked": "amass biomedcore, 0 records for the pair",
  "graph_nodes": ["SPOKE:BiologicalProcess:GO:0032543", "SPOKE:..."],
  "derived_from": "SIRT1 activation extends human healthspan via mitochondrial biogenesis"
}
```

`status` is one of `ESTABLISHED | CONTESTED | UNVERIFIED`. `evidence` entries are
`{"pmid", "how", "url"}` where `how` records *the way it was verified* — knockout
mouse, human RCT, epidemiological association — which is what the user asked for
and what lets the next team judge whether the verification actually transfers to
humans. An `UNVERIFIED` premise carries empty `evidence` plus `absence_checked`,
so "nobody has shown this" is a recorded query result rather than a silence.

`unverified_premises` is the subset with `status: UNVERIFIED` — the gaps the next
team's hypotheses should target. The full list goes in `knowledge_graph` so PLAN
can see what is already settled and avoid re-proposing it.

`knowledge_graph` renders as BioDisco's Scientist input, since that is the shape
an LLM consumes well and upstream `SpokePath` already carries it:

```
Nodes: SIRT1 (Protein), PGC-1alpha (Protein), mitochondrial biogenesis
       (Biological Process), human healthspan (Phenotype)
Direct Edges: SIRT1 -deacetylates-> PGC-1alpha  [ESTABLISHED, PMID:...]
              PGC-1alpha -triggers-> mitochondrial biogenesis  [ESTABLISHED, PMID:...]
              mitochondrial biogenesis -extends-> human healthspan  [UNVERIFIED]
MultiHop Paths: SIRT1 -> PGC-1alpha -> mitochondrial biogenesis -> human healthspan
                [weakest link: the final edge]
```

**Confirm these field names with the consumer team before building.** A contract
neither side has agreed is worse than none.

## Built: `backend/grounding/premises.py`

`extract(question, *, triplifier, prober, sources, verifier, knowledge_base) -> Grounding`.
L0 `ClaudeTriplifier` (bare canonical entity names, change in the verb),
L1 `ClaudeProber`, L2 `AmassPaperRepository` + `AmassTrialRepository` +
`ClaudeVerifier` (one query per source and one verdict per link, capped at
`MAX_LINKS`; the verifier sees whole abstracts), L3 deterministic `statement`
+ `render_graph`. Wired into `backend/agent/loop.py::_grounding_text` via
`scripts.run_grounding.ground`.

**Reproducibility.** Every Claude reply *and* every Amass query is cached in
`runs/knowledge.db` by content hash. Within one knowledge base the same
question replays byte-identical premises in under a second. Across a wiped
cache Claude may pick a different L1 chain (observed: PGC-1alpha/oxidative
stress vs a senescence route), so treat the knowledge base as part of the
result — archive it with the run, do not delete it to "refresh".

**Hypotheses (L4) — the frame.** Follows `docs/reference` "What is a good
hypothesis": the question is a ladder of claims, each needing its own kind
of evidence and carrying a grade; the hypothesis is the weakest *causal*
link restated as an interventional prediction, with a falsification
criterion, and a "why it exists" block made of the established links above
it, the contested ones beside it, and the recorded absence it fills. There
is little creative room by design: the generator may choose only the verb,
wording, intervention, readout, model system and falsification — subject
and object are the weak link's own, and one hypothesis per link survives.
`supported_by` / `conflicts_with` / `missing` are computed from the graph,
never written by the model.

**Hypotheses (L4) — the seam for the other team.**
`backend/grounding/hypotheses.py::HypothesisGenerator` is one method,
`generate(grounding) -> list[Hypothesis]`. Ours is
`adapters.ClaudeHypothesisGenerator`; a replacement is passed to
`premises.extract(generator=...)` in `scripts/run_grounding.py::ground` and
nothing else changes. Every generator's output goes through the same
deterministic `select()` filter: targets a known premise, at most 20 words,
no compound connectives, subject and object are graph nodes, has
intervention + readout + model system, one hypothesis per triple. Survivors
reach PLAN as "use these, never merge or extend"; drops are logged with the
one reason, on the question node.

**Modes and models.** `mode=fast|normal` on `POST /api/run` (toggle in the
compose dialog, default fast) and `--fast` on the scripts. Fast: 4 links,
1500-char abstracts, 10 trials per query, no second-look search — about half
the time and cost. Both modes keep L0, the L2 verdicts and L4 on the main
model; only the L1 probe runs on Haiku. Haiku verdicts were tried and
rejected: on identical records it called every link ESTABLISHED, including
biogenesis → human healthspan, so nothing was left to hypothesize about.

**Live progress.** `grounding_step` SSE events fire as each stage lands
(L0 triples + destination, L1 links, one per L2 verdict, L4 counts); the
progress view draws the stage rail, the claims, and every link turning
colour as its verdict arrives, from the first seconds of a run.

**Speed.** L2 verifies links in a thread pool (`MAX_LINKS` workers), so a
cold run is ~1 min instead of ~4.5; a warm run is under a second. The
remaining cost is the agent loop itself (PLAN → tools → REVISE → REPORT,
~2 min), which the grounding does not touch.

**Trajectory in the app.** Rendered in the browser, not fetched:
`frontend/src/lib/trajectory.ts` rebuilds this same graph — the node ids
above, the `asks`/verb/`evidence`/`tests` edges, the virtual
`subject`/`object`/`tested_by` links `kgviz/graph.py::load_graph` adds, and
its sorted BFS/DFS walk (checked identical on the same fixture) — from the
run's own `grounding_step` events while the grounding runs (links appear at
L1 as "checking…" and take their verdict colour as each L2 lands) and from
the final `grounding` event once it is done, so it works on the stateless
Vercel deployment where `runs/knowledge.db` never persists.
`frontend/src/components/KnowledgeTrajectory.tsx` is `kgviz/viewer.html`
ported to React, shown in `ProgressView` during the run and in
`ResultsView` afterwards. Its right-hand "Activation path" is stage-ordered
(L0 split, L1 links, L2 verdict per link with rationale, L4 hypotheses with
falsification), not BFS order. What the in-browser version cannot show is
what only the database holds — other runs of the same question and each
link's verdict history; `GET /api/trajectory?question=` (graph + walk +
reasoning log) and the sidecar `python -m scripts.run_trajectory --serve`
remain for local use, where the knowledge base does persist.

**Clean-room check.** `GROUNDING_KB=runs/clean_N.db python scripts/run_demo.py`
runs against a fresh base; `python -m scripts.check_trajectory <report.json>...`
confirms every final hypothesis is a knowledge-base hypothesis node whose
target premise lies on the question's walk, and reports how many statements
all runs share.

**Clean-room results (2026-09-12, four sequential runs, fresh base each).**
The core of the chain is stable across cold starts — the same five links
with the same verdict every time:

| link | 4/4 verdict | hypothesis in |
|---|---|---|
| SIRT1 → mitochondrial biogenesis | CONTESTED | 4/4 |
| mitochondrial biogenesis → human healthspan | UNVERIFIED | 4/4 |
| SIRT1 → human healthspan | UNVERIFIED | 3/4 (one dropped as compound) |
| SIRT1 → PGC-1alpha | ESTABLISHED | — |
| PGC-1alpha → mitochondrial biogenesis | ESTABLISHED | — |

What varies is the L1 elaboration downstream of biogenesis (respiratory
capacity / ATP / mitochondrial function / energy metabolism → ROS or
oxidative stress → damage or senescence): a different route each cold
start, each verified on its own merits. Hypothesis *sentences* differ run to
run; the unit that reproduces is (target link, human model system,
falsification), which is what the knowledge base records and the trajectory
check verifies. `check_trajectory` passed for all four reports: every final
hypothesis PLAN ranked was a knowledge-base hypothesis aimed at a premise on
the question's trajectory.

Known gap: when the filter drops the only hypothesis for a weak link (seq_2,
compound claim), that link goes to PLAN without a candidate. A retry for
uncovered links is the next step.

**Audit.** Every question, link, verdict, evidence record and hypothesis is a node in the
knowledge base; `verify` steps append per run, never overwrite.
`python -m scripts.run_grounding --kb` prints the whole thing readably. A
graph view should render from these tables, not from the run JSON.

**SPOKE — checked, not wired.** The API is keyless and works
(`search/{Type}/{query}`, `neighborhood/{Type}/name/{value}`), but:
BiologicalProcess search returns 500, there is no Disease/Symptom node for
healthspan or aging, edges are dataset-typed (`UPREGULATES_OGuG` from
CMAP/LINCS) rather than mechanistic verbs, and there is no path endpoint. It
could only confirm gene-gene edges literature already establishes, and says
nothing about the organismal links that come back UNVERIFIED.

## Original sketch — `grounding.py`, four functions

```python
def extract(question: str, *, mock: bool = True) -> tuple[list[dict], dict]:
    """The integration entry point. Returns (unverified_premises, knowledge_graph)."""
```

- `assess_and_triplify(question)` — L0. One Claude call returning
  `{coherent: bool, why: str, triples: [{subject, verb, object}]}`. An incoherent
  question returns empty premises and the reason, rather than fabricating structure.
- `probe_hypotheses(triples)` — L1. One Claude call, explicitly instructed to use
  no external knowledge, producing candidate triples not present in the input.
- `activate(probes)` — L2. For each probe, SPOKE for a curated relationship and
  Amass for literature. Reuse upstream: `scripts/spoke_amass_hypothesis.py` has
  working `spoke_search_nodes` / `spoke_multi_hop_paths` / `amass_evidence_search`,
  and the consumer repo has `backend/tools/amass_tool.py`. Port, do not rewrite.
  Verdict per probe: literature hits → `ESTABLISHED`; SPOKE edge but no
  literature → `UNVERIFIED` (the interesting case); neither → drop.
- `synthesise(probes, verdicts)` — L3. One Claude call turning verdicts into
  premises with rendered statements.

Cache layer: `backend/grounding/knowledge_base.py` retargeted — SPOKE nodes/edges
instead of MeSH co-occurrence, keyed per session or per project. Keep the
prompt-hash LLM cache, since the consumer's `plan_prompt` is deterministic-ish
and ours should be too. Keep `steps` so "how it was verified" is recoverable.

## Three confirmed bugs — FIXED during the move

Found by reading upstream code, no API credits spent. All three are already corrected in `backend/grounding/adapters.py`:

1. **Response shape.** The spike reads `response.json()["data"]["records"]`.
   Upstream `src/longevity/tools/amass_trials.py` — *"Verified live 2026-09-11
   with a real AMASS_API_KEY"* — uses `.get("data", [])`. **`data` is an array.**
2. **`temperature=0` breaks Claude 5.** `backend/grounding/adapters.py` passes it to
   `ChatAnthropic`; upstream `llm.py:143` deliberately omits it because the
   Claude 5 family rejects it with HTTP 400 (now documented in CLAUDE.md rule 6).
   Every live LLM call in the spike would have failed.
3. **`max_tokens` unset** — `ChatAnthropic` defaults to 1024; upstream raises it.
   Moot if `grounding.py` uses the raw `anthropic` SDK, which requires it explicitly.

## Verification

```bash
PY=~/miniforge3/envs/hypspeak/bin/python

$PY -m pytest -q                                   # whole suite, offline
$PY -m ruff check --select F backend/grounding scripts/run_grounding.py tests
$PY -m scripts.run_grounding --fixtures            # replay, no network
$PY -m scripts.run_grounding "<question>" --triples   # L0 only, Anthropic key
$PY -m scripts.run_grounding "<question>" --premises  # L0-L3, Anthropic + Amass keys

# end to end, live
$PY scripts/run_demo.py \
  "Does activating SIRT1 plausibly extend human healthspan via improved \
mitochondrial biogenesis, and what is the strongest next experiment to test that mechanism?"
```

The SIRT1 question is the acceptance case, and the offline selftest asserts it
end to end against recorded SPOKE/Amass responses:

1. L0 splits the two asks — the experiment request does not become a triple.
2. "via" produces **two** links, not one claim.
3. L1 inserts PGC-1α as an intermediary without any external lookup.
4. L2 returns a **mixed** verdict set — the molecular links `ESTABLISHED`, the
   organismal link `UNVERIFIED`. A run where every link comes back the same
   status is a bug, not a result.
5. `unverified_premises` is non-empty and contains the
   `mitochondrial biogenesis → extends → human healthspan` link.
6. Every `UNVERIFIED` premise carries `absence_checked`, so the absence is a
   recorded query rather than a silence.
7. An incoherent question yields empty premises plus a stated reason, and does
   not crash PLAN.
8. The same question twice produces identical premises via cache hits.

## Noted, not acted on

- **SPOKE** — `https://spoke.rbvi.ucsf.edu/api/v1`, already wired upstream with
  `fixtures/spoke_{search,neighborhood,paths}_SYNTHETIC.json`. Design against it.
- **LangGraph** — already the house pattern (`src/longevity/graph.py`). A future
  workflow rewrite is node wiring, not a port.
- **Session vs project scoping** of the cache — user deferred it explicitly.
- **Nebius** — object storage for run archives first; Postgres only if SQLite
  actually becomes a bottleneck. The KB is the seam.
- **BioDisco** (arXiv 2508.01285) — Background → Explorer → Scientist → Critic →
  Reviewer → Refiner. We own Background + Explorer; teammate A the Scientist;
  teammate B the Critic/Reviewer/Refiner loop.
