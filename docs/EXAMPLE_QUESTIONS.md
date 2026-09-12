# Example questions

Ready-to-paste questions for testing the agent in the web UI
(http://localhost:8000). Each is a real, open-ended longevity/ageing
question the agent hasn't seen hardcoded anywhere, so it has to actually
plan, retrieve, and compute rather than pattern-match a canned answer.

## General / canonical

Does activating SIRT1 plausibly extend human healthspan via improved
mitochondrial biogenesis, and what is the strongest next experiment to
test that mechanism?

Does chronic mTOR inhibition via rapamycin plausibly extend human
lifespan, and what evidence distinguishes a healthspan effect from a
lifespan effect?

## Trial-heavy (exercises ClinicalTrials.gov / Amass trialcore)

Is there enough clinical trial evidence to say metformin extends healthy
lifespan in non-diabetic humans, independent of its glucose-lowering
effect?

Are senolytic drugs (e.g. dasatinib plus quercetin) far enough along in
human trials to be considered a plausible near-term anti-ageing
intervention?

## Gene/target-focused (exercises Open Targets / GenAge / enrichment)

Does the FOXO3 longevity-associated variant plausibly work through
improved cellular stress resistance, and what pathway would a gene
enrichment analysis need to confirm that?

Is KLOTHO a plausible drug target for slowing age-related cognitive
decline?

## Compound/mechanism-focused (exercises PubMed / Amass drugcore)

Does spermidine supplementation plausibly extend healthspan via induced
autophagy, and what is the strongest evidence for or against that
mechanism in humans?

Do NAD+ precursors (NMN or NR) plausibly reduce cellular senescence
markers in humans, or is the human evidence still preclinical-only?

## Higher-risk / contested (good for testing "state uncertainty" behavior)

Would reactivating telomerase in healthy adults plausibly extend
lifespan, and what cancer-risk evidence would have to be weighed against
that?

Does APOE4 carrier status change what an ageing intervention should
prioritize, and is there evidence any current intervention addresses
that specifically?

## Testing "switch a tool off"

Reuse any question above, then in `.env` remove one tool from
`ENABLED_TOOLS` (e.g. drop `open_targets` or `pubmed`), restart the
server, and re-run the same question — the evidence mix and citation set
in the report should visibly change. See `docs/DEMO_SCRIPT.md`.
