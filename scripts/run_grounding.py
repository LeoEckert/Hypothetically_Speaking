"""AI-Scientist CLI — Track 1, literature-to-hypothesis.

    python -m scripts.run_grounding "<question>"             live run
    python -m scripts.run_grounding "<question>" --capture   live run, records the fixture
    python -m scripts.run_grounding --fixtures               replay the recording, no network
    python -m scripts.run_grounding "<question>" --triples   L0 only: coherence + A -verb-> B
    python -m scripts.run_grounding "<question>" --premises [--fast]   L0-L4: premises + graph + hypotheses
    python -m scripts.run_grounding --kb                     audit view of everything the knowledge base holds

Live runs need TAVILY_API_KEY, AMASS_API_KEY and ANTHROPIC_API_KEY in the
environment. How they get there is up to the caller — the code just reads
os.environ with no fallback, so a plain export or `set -a; . .env; set +a`
both work.

stdout is the JSON contract the hypothesis generator consumes; progress goes to
stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.grounding import premises, stages
from backend.grounding.adapters import (
    ABSTRACT_CHARS,
    ABSTRACT_CHARS_FAST,
    AMASS_LIMIT,
    FIXTURE_PATH,
    MODEL,
    PROBE_MODEL,
    TRIAL_LIMIT_FAST,
    VERIFY_MODEL,
    AmassPaperRepository,
    AmassTrialRepository,
    ClaudeEntityExtractor,
    ClaudeHypothesisGenerator,
    ClaudeProber,
    ClaudeQuestionFormalizer,
    ClaudeRelevanceRanker,
    ClaudeTriplifier,
    ClaudeVerifier,
    RecordedRun,
    TavilyWebSearch,
)
from backend.grounding.domain import (
    RunTrace,
)
from backend.grounding.knowledge_base import SqliteKnowledgeBase


def output(trace: RunTrace) -> dict:
    return {
        "run_id": trace.run_id,
        "captured_at": trace.captured_at,
        "model": trace.model,
        "graph_as_of": trace.graph_as_of,
        "question": trace.question.model_dump(),
        # Diff two runs on this to see which stage diverged and whether its
        # input changed (different prompt_hash) or only its output did.
        "reasoning_trace": [step.model_dump() for step in trace.trace_steps],
        "ranked_evidence": [
            {
                "rank": position,
                "title": entry.paper.title,
                "doi": entry.paper.doi,
                "pmid": entry.paper.pmid,
                "score": entry.score,
                "why": entry.rationale,
            }
            for position, entry in enumerate(trace.ranked, start=1)
        ],
        "novel_claims": [
            {
                "claim_id": claim.claim_id,
                "a": claim.pair.a.name,
                "c": claim.pair.c.name,
                "verdict": claim.verdict.value,
                "bridges": [bridge.name for bridge in claim.pair.bridges],
                "direct_papers": claim.pair.direct_papers,
                "support": [
                    {"doi": paper.doi, "pmid": paper.pmid, "title": paper.title}
                    for paper in claim.support
                ],
                "reasoning": [step.model_dump() for step in claim.reasoning],
            }
            for claim in trace.claims
        ],
    }


RUNS_DIR = Path("runs")


def archive(trace: RunTrace) -> None:
    """Every run leaves a file. Two of these diffed is the reproducibility story."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{trace.run_id}.json"
    path.write_text(trace.model_dump_json(indent=2))
    print(f"run archived: {path}", file=sys.stderr)


def live(question: str, capture: bool, graph_as_of: str | None = None) -> RunTrace:
    knowledge_base = SqliteKnowledgeBase()
    trace = stages.run(
        question,
        formalizer=ClaudeQuestionFormalizer(knowledge_base),
        web=TavilyWebSearch(),
        extractor=ClaudeEntityExtractor(knowledge_base),
        papers=AmassPaperRepository(),
        ranker=ClaudeRelevanceRanker(knowledge_base),
        knowledge_base=knowledge_base,
        model=MODEL,
        graph_as_of=graph_as_of,
    )
    archive(trace)
    if capture:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(trace.model_dump_json(indent=2))
        print(f"captured: {FIXTURE_PATH}", file=sys.stderr)
    return trace


def replay() -> RunTrace:
    recorded = RecordedRun.load()
    print(f"replaying recorded question: {recorded.trace.raw_question}", file=sys.stderr)
    # A fresh in-memory knowledge base, so the replay reproduces the recorded
    # run rather than mixing with whatever runs/knowledge.db accumulated.
    return stages.run(
        recorded.trace.raw_question,
        formalizer=recorded,
        web=recorded,
        extractor=recorded,
        papers=recorded,
        ranker=recorded,
        knowledge_base=SqliteKnowledgeBase(":memory:"),
        run_id=recorded.trace.run_id,
    )



def ground(question: str, ledger=None, fast: bool = False, on_progress=None) -> premises.Grounding:
    """L0-L4 with live adapters; the knowledge base caches every Claude call and
    Amass query. `ledger` (adapters.Ledger) receives every external call.

    L0, L2 verdicts and L4 stay on the main model in both modes (see the note
    on Haiku verdicts in adapters.py); L1 probing runs on PROBE_MODEL (Haiku).
    normal: 8 links, whole abstracts, 20 trials per query, a second-look search
            before a link is called unverified.
    fast:   4 links, 1500-char abstracts, 10 trials per query, no second look."""
    knowledge_base = SqliteKnowledgeBase()
    return premises.extract(
        question,
        triplifier=ClaudeTriplifier(knowledge_base, ledger, MODEL),
        prober=ClaudeProber(knowledge_base, ledger, PROBE_MODEL),
        sources=[
            AmassPaperRepository(knowledge_base, ledger),
            AmassTrialRepository(knowledge_base, ledger, TRIAL_LIMIT_FAST if fast else AMASS_LIMIT),
        ],
        verifier=ClaudeVerifier(knowledge_base, ledger, VERIFY_MODEL, ABSTRACT_CHARS_FAST if fast else ABSTRACT_CHARS),
        # The seam: swap in any object with generate(grounding) -> list[Hypothesis].
        generator=ClaudeHypothesisGenerator(knowledge_base, ledger, MODEL),
        knowledge_base=knowledge_base,
        fast=fast,
        on_progress=on_progress,
    )


def main(argv: list[str]) -> int:
    flags = {argument for argument in argv if argument.startswith("--")}
    positional = [argument for argument in argv if not argument.startswith("--")]
    # --as-of <timestamp> from an earlier run's JSON reads the graph as it stood
    # then, so a past run reproduces even after later runs added evidence.
    as_of = next((value for flag, value in zip(argv, argv[1:]) if flag == "--as-of"), None)
    if as_of in positional:
        positional.remove(as_of)

    if "--triples" in flags and len(positional) == 1:
        decomposition = ClaudeTriplifier(SqliteKnowledgeBase()).triplify(positional[0])
        for triple in decomposition.triples:
            print(f"{triple.subject} -{triple.verb}-> {triple.object}", file=sys.stderr)
        json.dump(decomposition.model_dump(), sys.stdout, indent=2)
        print()
        return 0
    if "--kb" in flags:
        print(SqliteKnowledgeBase().describe())
        return 0
    if "--premises" in flags and len(positional) == 1:
        grounding = ground(positional[0], fast="--fast" in flags)
        print(grounding.knowledge_graph, file=sys.stderr)
        for hypothesis in grounding.hypotheses:
            print(f"{hypothesis.id}: {hypothesis.statement}", file=sys.stderr)
        for hypothesis in grounding.rejected:
            print(f"rejected ({hypothesis.dropped}): {hypothesis.statement}", file=sys.stderr)
        json.dump(grounding.model_dump(mode="json"), sys.stdout, indent=2)
        print()
        return 0
    if "--fixtures" in flags:
        if not Path(FIXTURE_PATH).exists():
            print(f"no recording at {FIXTURE_PATH} — run once with --capture", file=sys.stderr)
            return 1
        trace = replay()
    elif len(positional) == 1:
        trace = live(positional[0], capture="--capture" in flags, graph_as_of=as_of)
    else:
        print(
            f'usage: {sys.argv[0]} "<question>" [--capture] [--as-of TS] [--triples | --premises] | --fixtures | --kb',
            file=sys.stderr,
        )
        return 2

    json.dump(output(trace), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
