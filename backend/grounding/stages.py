"""Application layer: stages 0-4 as plain functions taking ports.

Functions rather than classes — they hold no state. Each stage talks only to
the ports in `domain.py`, so swapping Tavily, Amass or Claude for a recorded
run is a change in `run()`'s arguments and nowhere else.

`run()` is also where provenance is written: every stage leaves a ReasoningStep
on the question node carrying its prompt hash, so two runs of the same question
can be diffed to the stage where they diverged.

Stages 5 (critique) and 6 (feedback loop) are not built yet; the reasoning log
and `KnowledgeBase.already_checked` are the hooks they will use.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from uuid import uuid4

from backend.grounding.domain import (
    MAX_GAP_CHECKS,
    SUPPORT_LIMIT,
    TOP_N,
    BiologicalEntity,
    KnowledgeBase,
    LiteratureQuery,
    NovelClaim,
    Paper,
    PaperRepository,
    QuestionFormalizer,
    RankedPaper,
    ReasoningStep,
    RelevanceRanker,
    RunTrace,
    ScientificQuestion,
    WebSearchRepository,
    claim_id,
    classify,
    concept_id,
    mentions,
    queries_for,
    question_id,
    utcnow,
)


def new_run_id() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _hash_of(adapter: object) -> str | None:
    # Only Claude-backed adapters carry one; stubs and replays do not.
    return getattr(adapter, "last_prompt_hash", None)


# --- stage 0 ---------------------------------------------------------------


def formalize(raw: str, formalizer: QuestionFormalizer) -> ScientificQuestion:
    question = formalizer.formalize(raw)
    if not question.is_narrow():
        # ponytail: warn rather than abort — a demo must not die on a vague
        # question. Tighten to a raise once the formalizer prompt is trusted.
        _log("stage 0: warning — question is still broad, some axes are unset")
    return question


# --- stage 1 ---------------------------------------------------------------


def ground(
    question: ScientificQuestion,
    web: WebSearchRepository,
    extractor,
) -> tuple[list, list[BiologicalEntity], list[LiteratureQuery]]:
    snippets = web.search(question)
    entities = extractor.extract(question, snippets)
    queries = queries_for(question, entities)
    return snippets, entities, queries


# --- stage 2 ---------------------------------------------------------------


def gather(queries: list[LiteratureQuery], repository: PaperRepository) -> list[Paper]:
    # ponytail: sequential loop. Fine at <= 5 queries against a 60 req/60s
    # limit; switch to httpx.AsyncClient if the query count grows.
    seen: dict[str, Paper] = {}
    for query in queries:
        for paper in repository.find(query):
            seen.setdefault(paper.amass_id, paper)
    return list(seen.values())


def index(
    papers: list[Paper],
    entities: list[BiologicalEntity],
    knowledge_base: KnowledgeBase,
    run_id: str,
) -> None:
    """Write papers, concepts and their co-occurrences into the knowledge base."""
    for entity in entities:
        knowledge_base.upsert_concept(entity, run_id)

    for paper in papers:
        paper_node = knowledge_base.upsert_paper(paper, run_id)
        hits = [entity for entity in entities if mentions(paper, entity)]
        for entity in hits:
            knowledge_base.link_mentions(paper_node, concept_id(entity.name), run_id)
        for position, first in enumerate(hits):
            for second in hits[position + 1 :]:
                knowledge_base.observe_co_occurrence(
                    paper_node, concept_id(first.name), concept_id(second.name), run_id
                )


# --- stage 3 ---------------------------------------------------------------


def rank_all(
    question: ScientificQuestion,
    papers: list[Paper],
    ranker: RelevanceRanker,
    top_n: int = TOP_N,
) -> list[RankedPaper]:
    known = {paper.amass_id for paper in papers}
    ranked = [entry for entry in ranker.rank(question, papers) if entry.paper.amass_id in known]
    ranked.sort(key=lambda entry: entry.score, reverse=True)
    return ranked[:top_n]


# --- stage 4 ---------------------------------------------------------------


def assess_novelty(
    papers: list[Paper],
    repository: PaperRepository,
    knowledge_base: KnowledgeBase,
    run_id: str,
    limit: int = MAX_GAP_CHECKS,
    as_of: str | None = None,
) -> list[NovelClaim]:
    """Turn knowledge-base gaps into verdicts, recording every one.

    Rejected pairs are recorded too — that is what stops a later round from
    re-checking them. `as_of` pins which version of the accumulated graph is
    read, so a past run stays reproducible after later runs add evidence.
    """
    claims: list[NovelClaim] = []
    for pair in knowledge_base.gap_candidates(limit=limit, as_of=as_of):
        direct = repository.count_direct(pair.a.name, pair.c.name)
        pair = pair.model_copy(update={"direct_papers": direct})
        verdict = classify(direct, len(pair.bridges))

        step = ReasoningStep(
            node_id=claim_id(pair.a, pair.c),
            stage="novelty",
            verdict=verdict.value,
            rationale=(
                f"{direct} direct paper(s) for '{pair.a.name}' + '{pair.c.name}', "
                f"{len(pair.bridges)} bridging concept(s): "
                f"{', '.join(bridge.name for bridge in pair.bridges)}"
            ),
            run_id=run_id,
            at=utcnow(),
        )
        knowledge_base.record_step(step)

        support = [paper for paper in papers if mentions(paper, pair.a) or mentions(paper, pair.c)][
            :SUPPORT_LIMIT
        ]

        claims.append(
            NovelClaim(
                claim_id=step.node_id,
                pair=pair,
                verdict=verdict,
                support=support,
                reasoning=[step],
            )
        )
    return claims


# --- the whole run ---------------------------------------------------------


def run(
    raw_question: str,
    *,
    formalizer: QuestionFormalizer,
    web: WebSearchRepository,
    extractor,
    papers: PaperRepository,
    ranker: RelevanceRanker,
    knowledge_base: KnowledgeBase,
    run_id: str | None = None,
    model: str = "",
    graph_as_of: str | None = None,
) -> RunTrace:
    run_id = run_id or new_run_id()
    node = question_id(raw_question)
    trail: list[ReasoningStep] = []

    def remember(stage: str, verdict: str, rationale: str, source: object = None) -> None:
        step = ReasoningStep(
            node_id=node,
            stage=stage,
            verdict=verdict,
            rationale=rationale,
            run_id=run_id,
            at=utcnow(),
            prompt_hash=_hash_of(source),
        )
        knowledge_base.record_step(step)
        trail.append(step)

    question = formalize(raw_question, formalizer)
    remember(
        "formalize",
        "narrow" if question.is_narrow() else "broad",
        f"mechanism={question.mechanism!r} cell_type={question.cell_type!r} "
        f"endpoint={question.endpoint!r} time_horizon={question.time_horizon!r}",
        formalizer,
    )
    _log(f"stage 0: {question.mechanism or '(no mechanism)'} / {question.cell_type or '-'}")

    snippets, entities, queries = ground(question, web, extractor)
    remember(
        "ground",
        f"{len(entities)} entities",
        f"{len(snippets)} snippets -> "
        f"entities=[{', '.join(entity.name for entity in entities)}] -> "
        f"queries=[{'; '.join(query.text for query in queries)}]",
        extractor,
    )
    _log(f"stage 1: {len(snippets)} snippets, {len(entities)} entities, {len(queries)} queries")

    gathered = gather(queries, papers)
    index(gathered, entities, knowledge_base, run_id)
    # Read after indexing, so this run's own evidence is inside the snapshot.
    graph_as_of = graph_as_of or utcnow()
    remember(
        "gather",
        f"{len(gathered)} papers",
        f"from {len(queries)} queries; graph_as_of={graph_as_of}; "
        f"ids=[{', '.join(paper.amass_id for paper in gathered)}]",
    )
    _log(f"stage 2: {len(gathered)} papers after dedupe, indexed")

    ranked = rank_all(question, gathered, ranker)
    remember(
        "rank",
        f"{len(ranked)} ranked",
        f"order=[{', '.join(entry.paper.amass_id for entry in ranked)}]",
        ranker,
    )
    _log(f"stage 3: {len(ranked)} ranked")

    claims = assess_novelty(gathered, papers, knowledge_base, run_id, as_of=graph_as_of)
    open_claims = [claim for claim in claims if claim.verdict.value == "OPEN"]
    _log(f"stage 4: {len(claims)} pairs checked, {len(open_claims)} OPEN")

    return RunTrace(
        run_id=run_id,
        captured_at=utcnow(),
        model=model,
        graph_as_of=graph_as_of,
        raw_question=raw_question,
        question=question,
        snippets=snippets,
        entities=entities,
        queries=queries,
        papers=gathered,
        ranked=ranked,
        claims=claims,
        trace_steps=trail,
    )
