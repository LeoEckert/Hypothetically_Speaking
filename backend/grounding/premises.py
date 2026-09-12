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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
# come first so they are never the ones cut. Fast mode checks the L0 claims
# plus one hop of elaboration and skips the second-look search.
MAX_LINKS = 8
FAST_LINKS = 4


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


def retrieve(queries: list[str], sources: list, seen: dict[str, Paper] | None = None) -> list[Paper]:
    """Union of every source over every query; `seen` dedupes across rounds."""
    seen = {} if seen is None else seen
    fresh: list[Paper] = []
    for text in queries:
        for source in sources:
            for paper in source.find(LiteratureQuery(text=text)):
                if paper.amass_id not in seen:
                    seen[paper.amass_id] = paper
                    fresh.append(paper)
    return fresh


def second_look_queries(link: Triple) -> list[str]:
    """Before calling a link UNVERIFIED, look once more with the verb in the
    query and, for human outcomes, for trials. A little room, not a hunt."""
    queries = [f"{link.subject} {link.verb} {link.object}"]
    if "human" in link.object.lower():
        queries.append(f"{link.subject} {link.object} randomized trial")
    return queries


def activate(link: Triple, sources: list, verifier, second_look: bool = True) -> tuple[PremiseStatus, list, str | None, str, str | None]:
    """L2 for one link. Returns (status, evidence, absence_checked, why, prompt_hash)."""
    seen: dict[str, Paper] = {}
    retrieve([f"{link.subject} {link.object}"], sources, seen)
    verification = verifier.verify(link, list(seen.values())) if seen else None
    rounds = 1
    if second_look and (verification is None or verification.status is PremiseStatus.UNVERIFIED):
        fresh = retrieve(second_look_queries(link), sources, seen)
        rounds = 2
        if fresh:
            verification = verifier.verify(link, list(seen.values()))
    searches = f"{rounds} search{'es' if rounds > 1 else ''}"
    if verification is None:
        return PremiseStatus.UNVERIFIED, [], f"{SOURCES}, 0 records over {searches}", "no literature retrieved", None
    digest = getattr(verification, "prompt_hash", None)
    if verification.status is PremiseStatus.UNVERIFIED:
        # Topical papers are not evidence for the link; the recorded query is.
        absence = f"{SOURCES}, {len(seen)} records over {searches}, none verify the link"
        return PremiseStatus.UNVERIFIED, [], absence, verification.why, digest
    return verification.status, verification.evidence, None, verification.why, digest


def render_graph(premises: list[Premise], destination: str = "") -> str:
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
    lines = ["Nodes: " + ", ".join(nodes)]
    if destination:
        lines.append(f"Destination (the outcome asked about): {destination}")
    lines += ["Direct Edges:"] + [f"  {edge}" for edge in edges]
    lines.append("Weakest links: " + ("; ".join(weakest) if weakest else "none — every link verified"))
    return "\n".join(lines)


def extract(
    question: str, *, triplifier, prober, sources: list, verifier, generator=None,
    knowledge_base=None, run_id: str | None = None, fast: bool = False, on_progress=None,
) -> Grounding:
    """The integration entry point. `generator` is any HypothesisGenerator.
    `on_progress(event)` fires as each stage lands, so a UI can draw the
    chain while the verdicts are still coming in."""
    run_id = run_id or new_run_id()
    node = question_id(question)
    max_links = FAST_LINKS if fast else MAX_LINKS

    def progress(event: dict) -> None:
        if on_progress is not None:
            on_progress(event)

    def remember(stage: str, verdict: str, rationale: str, adapter=None) -> None:
        if knowledge_base is None:
            return
        knowledge_base.record_step(
            ReasoningStep(
                node_id=node, stage=stage, verdict=verdict, rationale=rationale, run_id=run_id,
                at=utcnow(), prompt_hash=getattr(adapter, "last_prompt_hash", None),
            )
        )

    decomposition = triplifier.triplify(question)
    if knowledge_base is not None:
        knowledge_base._upsert_node(node, "question", question, {}, run_id)
        knowledge_base.set_payload(node, {"destination": decomposition.destination})
    remember(
        "triplify", "coherent" if decomposition.coherent else "incoherent",
        decomposition.why + " | " + "; ".join(Premise.render(t) for t in decomposition.triples), triplifier,
    )
    progress({
        "stage": "L0", "coherent": decomposition.coherent, "why": decomposition.why,
        "triples": [t.model_dump() for t in decomposition.triples], "destination": decomposition.destination,
    })
    if not decomposition.coherent or not decomposition.triples:
        _log(f"L0: not a coherent question — {decomposition.why}")
        return Grounding(run_id=run_id, question=question, coherent=False, why=decomposition.why)
    for triple in decomposition.triples:
        _log(f"L0: {Premise.render(triple)}")
    _log(f"L0: destination = {decomposition.destination or '(none named)'}")

    probes = prober.probe(decomposition.triples)
    candidates = _dedupe(decomposition.triples + probes)
    links, cut = candidates[:max_links], candidates[max_links:]
    progress({"stage": "L1", "links": [t.model_dump() for t in links], "cut": len(cut)})
    remember(
        "probe", f"{len(links)} links",
        "; ".join(Premise.render(t) for t in links)
        + (" || not checked (over MAX_LINKS): " + "; ".join(Premise.render(t) for t in cut) if cut else ""),
        prober,
    )
    _log(f"L1: {len(links)} links to check" + (f", {len(cut)} cut" if cut else ""))

    # Links are independent, so verify them side by side. Each verdict is
    # announced as it lands; the results are then assembled in link order, so
    # the output is the same as the sequential one.
    verdicts: list = [None] * len(links)
    with ThreadPoolExecutor(max_workers=MAX_LINKS) as pool:
        futures = {pool.submit(activate, link, sources, verifier, not fast): i for i, link in enumerate(links)}
        for future in as_completed(futures):
            i = futures[future]
            verdicts[i] = future.result()
            progress({"stage": "L2", "link": links[i].model_dump(), "status": verdicts[i][0].value, "why": verdicts[i][3]})

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
        triples=decomposition.triples, destination=decomposition.destination,
        premises=premises, knowledge_graph=render_graph(premises, decomposition.destination),
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
        if knowledge_base is not None:
            knowledge_base.upsert_hypothesis(hypothesis, run_id)
    grounding.rejected = [h for h, _ in dropped]
    progress({"stage": "L4", "kept": len(kept), "rejected": len(dropped)})
    remember(
        "hypothesize", f"{len(kept)} kept, {len(dropped)} dropped",
        "; ".join(f"{h.id} {h.statement}" for h in kept)
        + (" || dropped: " + "; ".join(f"{h.statement} ({r})" for h, r in dropped) if dropped else ""),
        generator,
    )
    grounding.hypotheses = kept
    return grounding
