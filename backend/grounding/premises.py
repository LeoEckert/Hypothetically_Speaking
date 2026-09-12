"""Question -> premises + knowledge graph, the chain PLAN is grounded on.

L0 triplify (Claude) -> L1 probe (Claude, no sources) -> L2 activate (Amass
publications + trials, Claude verdict per link) -> L3 render premises and the
graph text. Stages are functions taking ports, like `stages.py`, so a recorded
or stubbed adapter swaps in for tests.

Reproducibility: every Claude reply and every Amass query is cached in the
knowledge base by content hash, so the same question replays the same
literature and the same verdicts. Every link is also persisted there with its
verdict history, so a scientist can audit what the graph rests on.

ponytail: SPOKE is not a source. Its API has no node for "mitochondrial
biogenesis" or "healthspan" (BiologicalProcess search 500s, no Disease node),
so it could only confirm gene-gene edges that literature already establishes.
Add a port here if that changes.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from backend.grounding.domain import (
    Grounding,
    LiteratureQuery,
    Paper,
    Premise,
    PremiseStatus,
    ReasoningStep,
    Triple,
    question_id,
    utcnow,
)
from backend.grounding.hypotheses import select
from backend.grounding.stages import new_run_id

SOURCES = "amass biomedcore+trialcore"
# Each link costs one query per source and one Claude verdict; the L0 triples
# come first so they are never the ones cut.
MAX_LINKS = 8


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _dedupe(triples: list[Triple]) -> list[Triple]:
    """One link per (subject, object). Retrieval queries the two ends, not the
    verb, so two verbs for the same pair would be the same evidence twice;
    the first spelling (L0's, if any) wins."""
    seen: dict[tuple[str, str], Triple] = {}
    for triple in triples:
        seen.setdefault((triple.subject.lower(), triple.object.lower()), triple)
    return list(seen.values())


def _derived_from(link: Triple, originals: list[Triple]) -> str:
    """The L0 triple this link elaborates: the one sharing an endpoint, else the first."""
    for original in originals:
        if link.subject.lower() in original.subject.lower() or link.object.lower() in original.object.lower():
            return Premise.render(original)
    return Premise.render(originals[0]) if originals else Premise.render(link)


def retrieve(link: Triple, sources: list) -> list[Paper]:
    query = LiteratureQuery(text=f"{link.subject} {link.object}")
    seen: dict[str, Paper] = {}
    for source in sources:
        for paper in source.find(query):
            seen.setdefault(paper.amass_id, paper)
    return list(seen.values())


def activate(link: Triple, sources: list, verifier) -> tuple[PremiseStatus, list, str | None, str, str | None]:
    """L2 for one link. Returns (status, evidence, absence_checked, why, prompt_hash)."""
    retrieved = retrieve(link, sources)
    if not retrieved:
        return PremiseStatus.UNVERIFIED, [], f"{SOURCES}, 0 records for the pair", "no literature retrieved", None
    verification = verifier.verify(link, retrieved)
    digest = getattr(verification, "prompt_hash", None)
    if verification.status is PremiseStatus.UNVERIFIED:
        # Topical papers are not evidence for the link; the recorded query is.
        absence = f"{SOURCES}, {len(retrieved)} records for the pair, none verify the link"
        return PremiseStatus.UNVERIFIED, [], absence, verification.why, digest
    return verification.status, verification.evidence, None, verification.why, digest


def render_graph(premises: list[Premise]) -> str:
    """BioDisco-style Scientist input: nodes, edges with status, the weakest link."""
    nodes: list[str] = []
    for premise in premises:
        for name in (premise.subject, premise.object):
            if name not in nodes:
                nodes.append(name)
    edges = []
    for premise in premises:
        labels = ", ".join(label for label in (e.label() for e in premise.evidence) if label)
        tag = f"{premise.status.value}, {labels}" if labels else premise.status.value
        edges.append(f"{premise.subject} -{premise.verb}-> {premise.object}  [{tag}]")
    weakest = [Premise.render(p) for p in premises if p.status is PremiseStatus.UNVERIFIED]
    lines = ["Nodes: " + ", ".join(nodes), "Direct Edges:"] + [f"  {edge}" for edge in edges]
    lines.append("Weakest links: " + ("; ".join(weakest) if weakest else "none — every link verified"))
    return "\n".join(lines)


def extract(
    question: str, *, triplifier, prober, sources: list, verifier, generator=None,
    knowledge_base=None, run_id: str | None = None,
) -> Grounding:
    """The integration entry point. `generator` is any HypothesisGenerator."""
    run_id = run_id or new_run_id()
    node = question_id(question)

    def remember(stage: str, verdict: str, rationale: str, adapter=None) -> None:
        if knowledge_base is None:
            return
        knowledge_base.record_step(
            ReasoningStep(
                node_id=node, stage=stage, verdict=verdict, rationale=rationale, run_id=run_id,
                at=utcnow(), prompt_hash=getattr(adapter, "last_prompt_hash", None),
            )
        )

    if knowledge_base is not None:
        knowledge_base._upsert_node(node, "question", question, {}, run_id)

    decomposition = triplifier.triplify(question)
    remember(
        "triplify", "coherent" if decomposition.coherent else "incoherent",
        decomposition.why + " | " + "; ".join(Premise.render(t) for t in decomposition.triples), triplifier,
    )
    if not decomposition.coherent or not decomposition.triples:
        _log(f"L0: not a coherent question — {decomposition.why}")
        return Grounding(run_id=run_id, question=question, coherent=False, why=decomposition.why)
    for triple in decomposition.triples:
        _log(f"L0: {Premise.render(triple)}")

    probes = prober.probe(decomposition.triples)
    links = _dedupe(decomposition.triples + probes)[:MAX_LINKS]
    remember("probe", f"{len(links)} links", "; ".join(Premise.render(t) for t in links), prober)
    _log(f"L1: {len(links)} links to check")

    # Links are independent, so verify them side by side; map() keeps the
    # order, so the output is the same as the sequential one.
    with ThreadPoolExecutor(max_workers=MAX_LINKS) as pool:
        verdicts = list(pool.map(lambda link: activate(link, sources, verifier), links))

    premises: list[Premise] = []
    for link, (status, evidence, absence, why, digest) in zip(links, verdicts):
        _log(f"L2: {Premise.render(link)} -> {status.value} ({why})")
        premise = Premise(
            subject=link.subject, verb=link.verb, object=link.object,
            statement=Premise.render(link), status=status, evidence=evidence,
            absence_checked=absence, derived_from=_derived_from(link, decomposition.triples),
        )
        premises.append(premise)
        if knowledge_base is not None:
            knowledge_base.upsert_premise(premise, node, run_id, why, digest)

    grounding = Grounding(
        run_id=run_id, question=question, coherent=True, why=decomposition.why,
        triples=decomposition.triples, premises=premises, knowledge_graph=render_graph(premises),
    )
    if generator is None:
        return grounding

    kept, dropped = select(generator.generate(grounding), grounding)
    for hypothesis in kept:
        _log(f"L4: {hypothesis.id} {hypothesis.statement}")
        if knowledge_base is not None:
            knowledge_base.upsert_hypothesis(hypothesis, run_id)
    for hypothesis, reason in dropped:
        _log(f"L4: dropped ({reason}): {hypothesis.statement}")
    remember(
        "hypothesize", f"{len(kept)} kept, {len(dropped)} dropped",
        "; ".join(f"{h.id} {h.statement}" for h in kept)
        + (" || dropped: " + "; ".join(f"{h.statement} ({r})" for h, r in dropped) if dropped else ""),
        generator,
    )
    grounding.hypotheses = kept
    return grounding
