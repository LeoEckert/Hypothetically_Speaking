# Challenges - Track 1

<aside>
🧬

**Track 1 · Longevity Biology × AI — scientific challenges**

A flagship agentic challenge — **Build a Longevity AI Scientist** — plus five focused scientific challenges, each with a defined question, a required output and a suggested data stack. Choose one, or use them as a template for a question of your own.

</aside>

## 1 · Build a Longevity AI Scientist ⭐

*Question → evidence → experiment, end to end — the flagship challenge*

**The question.** Ageing research is bottlenecked by human bandwidth, not ideas. Can your team build an **AI scientist** — an agent, or a small team of agents — that takes a real longevity question and moves it forward without a human steering each step?

**Build:** an agent that forms a hypothesis, gathers and weighs the evidence, calls biological tools, runs an in-silico experiment and returns a cited, defensible answer. Example shapes:

- **Target triage agent** — mine literature and Open Targets, rank candidate targets by genetic evidence, sketch a binder with an open structure-prediction tool (e.g. Boltz) and write a cited target-validation memo.
- **Autonomous ageing-clock builder** — pull methylation or multi-omic data, train a clock, benchmark it against DunedinPACE and report honestly on where it fails.
- **Literature-to-hypothesis agent** — read a corpus of ageing papers and propose novel, testable hypotheses, each traceable to its sources.
- **In-silico intervention tester** — simulate a candidate intervention on a pathway and summarise the predicted mechanism and confidence.
- **Grounded science communicator** — turn a dense longevity finding into a legible, fully-cited brief — and a voice briefing a clinician or policymaker could actually listen to.

**Required output:**

1. A working agent that plans, retrieves, calls tools and revises without hand-holding
2. At least one real biological or data tool call inside the loop — not just text summarisation
3. A cited final report: what the evidence supports, what it doesn't, and the next experiment to run
4. Stated uncertainty and failure modes
5. A demo a judge could re-run, plus a recorded fallback

**The partner stack — provided to every team:**

- **Anthropic** — the agent brain: Claude models, Claude Agent SDK and MCP for reasoning, planning, tool-calling and grounded writing.
- **Nebius** — GPU compute and model hosting; Token Factory credits via QR at the venue.
- **Tavily** — live web retrieval over papers, trials and news; 8,000 credits per participant.
- **Amass** — scientific memory across literature, trials, patents and biological data, via app, API and MCP; $500 credits per team.
- **ElevenLabs** — turn findings into listenable, cited voice briefings; 1 month Creator per participant.
- **Lovable** — a demo-ready front-end, fast; Pro Plan 1 with 100 credits.
- **Open data** — Open Targets and the playbook dataset library for target–disease evidence, ageing clocks and public omics.

A **starter scaffold** (Claude + Nebius + Tavily + one memory layer + one bio tool) is provided on day one, so the 36 hours go into the science, not the plumbing.

**Evaluation:** scored on the hackathon's six weighted dimensions. For this challenge the bar is a real question moved forward with genuine autonomy — every claim traceable to a source, limits stated honestly, and an output a clinician or investor can understand in one pass. A rigorous answer to a narrow question beats a vague tour of a big one.

**What proves it works:** at least 95% of factual claims in the final report carry a working citation; the full run re-executes from a clean checkout in under 30 minutes; and judges can switch one tool off and watch the answer change — proof the tools are inside the loop, not decoration.

## 2 · Find the control point

*Ageing → mechanism*

**The question.** Given an ageing-associated molecular state, identify the process most plausibly limiting restoration of a younger, homeostatic state.

**Required output:**

1. Ranked mechanistic hypotheses
2. Evidence across tissues and cell types
3. Stated uncertainty
4. One experiment that could falsify the top hypothesis

**What proves it works:** the top-ranked hypothesis is supported by evidence in a held-out tissue or cell type the team never used, and a mentor scientist judges the falsification experiment genuinely executable.

**Suggested open-data stack:**

- **Tabula Muris Senis** (or other open ageing atlases) — age-associated molecular states
- **Human Protein Atlas (HPA)** — tissue, cell-type and subcellular localisation as a reality filter

## 3 · From phenotype to perturbation

*Mechanism → intervention*

**The question.** Starting from an ageing-associated phenotype or mechanism, identify an actionable target and a credible chemical perturbation predicted to move the system towards a healthier state.

**Required output:**

1. Target and perturbation, with predicted direction of effect
2. Independent evidence layers
3. Negative and control strategy
4. A testable validation experiment

**What proves it works:** the pipeline recovers at least two known target–compound pairs from a held-out set, with the predicted direction of effect matching the published literature.

**Suggested open-data stack:**

- **Human Protein Atlas (HPA)** — target expression and localisation
- **Broad Cell Painting / JUMP** — chemical and genetic phenotypic profiles
- **EUbOPEN** — high-quality chemical probes and matched inactive controls
- **IUPHAR/BPS Guide to Pharmacology** — curated target–ligand pharmacology

## 4 · What should we do next?

*Evidence → experiment*

**The question.** Given incomplete and potentially conflicting evidence around an ageing mechanism or intervention, choose the single next experiment with the highest expected information gain.

**Required output:**

1. Competing hypotheses
2. The proposed experiment
3. Predicted outcomes under each hypothesis
4. A decision rule — how each result would change target or intervention prioritisation

**Suggested open-data stack:**

- A curated multi-source package assembled from the resources above
- One evidence layer is deliberately withheld — part of the task is identifying what is missing, not pretending the available data are sufficient

**What proves it works:** the decision rule is written down before the withheld layer is revealed — and when it is revealed, the team shows whether the chosen experiment changes, and defends the outcome against a mentor panel.

## 5 · Curate the world's ageing data

*Messy studies → harmonised, provenance-tagged metadata*

**The question.** Single-cell ageing studies are scattered across public repositories with inconsistent sample metadata — replication and meta-analysis stall because nobody can tell which samples are comparable. Can your agents turn a messy study into clean, harmonised, fully-provenanced metadata?

**Build:** a supervisor-orchestrated multi-agent pipeline that, given a paper or a GEO accession, locates the linked files, extracts per-sample metadata (donor, age, sex, tissue, assay, treatment), harmonises values to standard ontologies, maps samples to donors, and issues a human-readable QA report.

**Required output:**

1. A harmonised sample–donor table for at least one well-structured and one deliberately messy ageing study
2. Per-field confidence scores and provenance pointers (source document and location)
3. A QA report that flags ambiguities for human review rather than guessing silently
4. Accuracy measured against a curator-reviewed reference set

**Possible sources:**

- **GEO**, **CZ CELLxGENE Census**, **Human Cell Atlas** and **Tabula Sapiens v2** — all in the playbook dataset library, with plenty of ageing scRNA-seq studies to practise on
- Open ontologies (MONDO, EFO, Cell Ontology, UBERON) via the free OLS API
- **Claude (Anthropic) Agent SDK** for orchestration · **Amass** for study context

**Evaluation:** extraction precision and recall against the reference set, ontology-mapping accuracy and provenance completeness — with human QA time saved as the headline metric. A strong bar from previous editions: ≥90% precision on a clean study, ≥80% on a messy one, and ≥98% of fields carrying a source pointer.

## 6 · Synthetic data for ageing clocks

*Scarce methylation data → validated synthetic cohorts*

**The question.** Ageing-clock research is throttled by data access: real methylation cohorts can take months of applications. Can you generate synthetic or augmented methylation data realistic enough that a clock trained on it holds up against one trained on real data alone?

**Build:** a pipeline that synthesises or augments DNA-methylation cohorts, ships a validation card (distributions, correlations, known age associations), and reports honestly where synthetic data helps and where it breaks.

**Required output:**

1. A synthetic or augmented methylation cohort with a validation card
2. The key experiment: a clock trained on augmented data vs the same clock trained on the original data, both scored on held-out real samples
3. Failure modes and privacy caveats, stated plainly

**Possible sources:**

- **DNA methylation datasets via Biolearn** — 40+ harmonised GEO datasets and 20+ reference clocks, including DunedinPACE and AltumAge — and **ClockBase**, both in the playbook dataset library
- **Nebius** GPU credits for the training runs

**Evaluation:** the augmented-data clock matches or beats the baseline on held-out real data — and the team can explain why, or why not.

## Why these resources are practical

| Resource | What it gives you | Access and licence |
| --- | --- | --- |
| Human Protein Atlas | Downloadable tissue, single-cell, cell-line and subcellular data | CC BY 4.0; check embedded third-party data |
| Cell Painting / JUMP | Images, features and metadata downloadable separately; public AWS, no account required | CC0 |
| EUbOPEN | Peer-reviewed chemical probes — potency, selectivity, cellular target engagement and, where feasible, matched inactive controls; chemogenomic set downloadable as CSV | Open download |
| Guide to Pharmacology | Downloadable target, ligand and interaction tables, plus REST access | ODbL; contents CC BY-SA 4.0 |

## How these challenges are run

- **Pre-curated data.** IDs, mappings and processed feature matrices are provided; raw-data links are optional extensions.
- **Held-out evaluation.** A tissue, perturbation, compound class or evidence layer is held back for final evaluation — build for generalisation, not just the visible data.
- **Uncertainty required.** Submissions must state uncertainty and a falsification criterion.
- **Validity over polish.** Biological validity and generalisation score higher than UI polish.
- **The flagship runs on the partner stack.** Challenge 1 teams build with Anthropic, Nebius, Tavily, Amass, ElevenLabs and Lovable — access and credit details are in the Tooling Partners section and the Friday technical briefing.

<aside>
🎯

**Choosing between them?**

Pick the question your team can answer with evidence over the weekend. A focused, falsifiable result beats a broad survey — mentors can help you scope during Friday's track Q&A and Saturday's rotations.

</aside>