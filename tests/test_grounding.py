"""Grounding pipeline: pure logic, the knowledge base, and record/replay.

Offline — no network, no API keys. Stub ports stand in for Tavily, Amass and
Claude, and the knowledge base runs on `:memory:`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.grounding import stages  # noqa: E402
from backend.grounding.adapters import RecordedRun, _parse_fence  # noqa: E402
from backend.grounding.domain import (  # noqa: E402
    BiologicalEntity,
    Decomposition,
    NoveltyVerdict,
    Paper,
    RankedPaper,
    ReasoningStep,
    RunTrace,
    ScientificQuestion,
    concept_id,
    classify,
    queries_for,
    question_id,
    utcnow,
)
from backend.grounding.knowledge_base import SqliteKnowledgeBase  # noqa: E402
from scripts.run_grounding import output  # noqa: E402


# --- stub ports -------------------------------------------------------------


class _StubFormalizer:
    def __init__(self, question):
        self.question = question

    def formalize(self, raw):
        return self.question


class _StubWeb:
    def __init__(self, snippets):
        self.snippets = snippets

    def search(self, question):
        return self.snippets


class _StubExtractor:
    def __init__(self, entities):
        self.entities = entities

    def extract(self, question, snippets):
        return self.entities


class _StubRepo:
    def __init__(self, papers, direct=None, once=False):
        self.papers = papers
        self.direct = direct or {}
        self.once = once
        self.served = False

    def find(self, query):
        if self.once and self.served:
            return []
        self.served = True
        return self.papers

    def count_direct(self, a, c):
        return self.direct.get(frozenset({a.lower(), c.lower()}), 0)


class _StubRanker:
    def __init__(self, scores):
        self.scores = scores

    def rank(self, question, papers):
        by_id = {paper.amass_id: paper for paper in papers}
        return [
            RankedPaper(
                paper=by_id.get(amass_id, Paper(amass_id=amass_id, title="ghost")),
                score=score,
                rationale="stub",
            )
            for amass_id, score in self.scores
        ]


# --- shared fixtures-by-hand ------------------------------------------------

BROAD = ScientificQuestion(text="why do we age")
NARROW = ScientificQuestion(
    text="...",
    mechanism="autophagy",
    cell_type="fibroblast",
    endpoint="SA-beta-gal",
    time_horizon="14 days",
)


def _entity(name, kind="gene"):
    return BiologicalEntity(name=name, kind=kind)


def _papers():
    return [
        Paper(amass_id="AMBC_1", title="first", doi="10.1/a", abstract="mTOR and autophagy"),
        Paper(amass_id="AMBC_2", title="second", pmid="222", abstract="autophagy in naked mole-rat"),
        Paper(amass_id="AMBC_1", title="first again", doi="10.1/dupe"),
    ]


def _queries():
    return queries_for(
        NARROW, [_entity("mTOR"), _entity("mTOR"), _entity("TP53"), _entity("SIRT1")], limit=2
    )


# --- pure rules -------------------------------------------------------------


def test_is_narrow_requires_all_four_axes():
    assert not BROAD.is_narrow()
    assert NARROW.is_narrow()


def test_queries_are_deterministic_deduped_and_capped():
    assert [q.text for q in _queries()] == ["autophagy mTOR", "autophagy TP53"]
    assert queries_for(BROAD, [_entity("mTOR")])[0].text == "why do we age mTOR"


def test_novelty_truth_table_at_every_boundary():
    assert classify(5, 9) is NoveltyVerdict.KNOWN
    assert classify(4, 9) is NoveltyVerdict.EMERGING
    assert classify(1, 0) is NoveltyVerdict.EMERGING
    assert classify(0, 2) is NoveltyVerdict.OPEN
    assert classify(0, 1) is NoveltyVerdict.UNSUPPORTED


def test_decomposition_parses_the_l0_fence():
    reply = (
        "```json\n"
        '{"coherent": true, "why": "named cause, mechanism, outcome", "triples": ['
        '{"subject": "SIRT1 activation", "verb": "improves", "object": "mitochondrial biogenesis"},'
        '{"subject": "mitochondrial biogenesis", "verb": "extends", "object": "human healthspan"}]}'
        "\n```"
    )
    decomposition = _parse_fence(reply, Decomposition)
    assert decomposition.coherent
    assert [(t.subject, t.verb, t.object) for t in decomposition.triples] == [
        ("SIRT1 activation", "improves", "mitochondrial biogenesis"),
        ("mitochondrial biogenesis", "extends", "human healthspan"),
    ]
    assert _parse_fence('{"coherent": false, "why": "no relation"}', Decomposition).triples == []


# --- stages -----------------------------------------------------------------


def test_gather_dedupes_across_and_within_queries():
    gathered = stages.gather(_queries(), _StubRepo(_papers()))
    assert [p.amass_id for p in gathered] == ["AMBC_1", "AMBC_2"]
    assert gathered[0].doi == "10.1/a", "first occurrence must win"


def test_rank_all_drops_invented_ids_sorts_and_truncates():
    gathered = stages.gather(_queries(), _StubRepo(_papers()))
    ranker = _StubRanker([("AMBC_2", 0.4), ("AMBC_999", 0.99), ("AMBC_1", 0.9)])
    ranked = stages.rank_all(NARROW, gathered, ranker)
    assert [r.paper.amass_id for r in ranked] == ["AMBC_1", "AMBC_2"]
    assert all(r.paper.title != "ghost" for r in ranked), "invented id must be dropped"
    assert len(stages.rank_all(NARROW, gathered, ranker, top_n=1)) == 1


# --- knowledge base ---------------------------------------------------------


def _graph():
    """a-b1-c, a-b2-c gives a/c two bridges and no direct link; a/d has one."""
    knowledge_base = SqliteKnowledgeBase(":memory:")
    for key in ("a", "b1", "b2", "c", "d"):
        knowledge_base.upsert_concept(_entity(key, "pathway"), "r-test")

    def observe(witness, left, right):
        knowledge_base.observe_co_occurrence(
            f"P:{witness}", concept_id(left), concept_id(right), "r-test"
        )

    for witness, (left, right) in enumerate(
        [("a", "b1"), ("a", "b2"), ("b1", "c"), ("b2", "c"), ("b1", "d"), ("a", "d")]
    ):
        observe(str(witness), left, right)
    return knowledge_base, observe


def test_gap_query_finds_the_gap_and_skips_direct_links():
    knowledge_base, _ = _graph()
    pairs = {(pair.a.name, pair.c.name) for pair in knowledge_base.gap_candidates()}
    assert ("a", "c") in pairs
    assert ("a", "d") not in pairs, "a direct co-occurrence disqualifies a gap"


def test_identical_evidence_produces_identical_gaps():
    knowledge_base, _ = _graph()
    first = [p.model_dump() for p in knowledge_base.gap_candidates()]
    second = [p.model_dump() for p in knowledge_base.gap_candidates()]
    assert first == second, "gaps must be stable, bridges included"


def test_as_of_reconstructs_the_graph_before_later_evidence():
    knowledge_base, observe = _graph()
    before = utcnow()
    observe("late", "a", "c")  # closes the a-c gap, but only from now on
    now_pairs = {(p.a.name, p.c.name) for p in knowledge_base.gap_candidates()}
    then_pairs = {(p.a.name, p.c.name) for p in knowledge_base.gap_candidates(as_of=before)}
    assert ("a", "c") not in now_pairs
    assert ("a", "c") in then_pairs


def test_observation_log_is_append_only():
    knowledge_base, observe = _graph()
    observe("late", "a", "c")
    count = knowledge_base.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 7, "observations must accumulate, never overwrite"


def test_reasoning_log_is_append_only_and_ordered():
    knowledge_base, _ = _graph()
    for verdict in ("OPEN", "REFINE"):
        knowledge_base.record_step(
            ReasoningStep(
                node_id="K:test",
                stage="novelty",
                verdict=verdict,
                rationale="stub",
                run_id="r-test",
                at=utcnow(),
            )
        )
    assert [s.verdict for s in knowledge_base.steps_for("K:test")] == ["OPEN", "REFINE"]
    assert knowledge_base.already_checked("K:test")
    assert not knowledge_base.already_checked("K:absent")


def test_llm_cache_replays_an_identical_prompt():
    knowledge_base, _ = _graph()
    knowledge_base.store_response("hash-1", "claude-sonnet-5", '{"entities": []}')
    assert knowledge_base.cached_response("hash-1") == '{"entities": []}'
    assert knowledge_base.cached_response("hash-absent") is None


# --- full run ---------------------------------------------------------------

# Two bridges are needed for OPEN, so the corpus gives mTOR and the naked
# mole-rat two shared neighbours and no paper covering both directly.
_CONCEPTS = [
    _entity("mTOR", "gene"),
    _entity("autophagy", "pathway"),
    _entity("proteostasis", "pathway"),
    _entity("naked mole-rat", "species"),
]
_CORPUS = [
    Paper(amass_id="AMBC_1", title="mTOR and autophagy in ageing", doi="10.1/a"),
    Paper(amass_id="AMBC_2", title="autophagy in the naked mole-rat", pmid="222"),
    Paper(amass_id="AMBC_3", title="mTOR drives proteostasis", doi="10.1/c"),
    Paper(amass_id="AMBC_4", title="proteostasis in the naked mole-rat", pmid="444"),
]


def _run():
    repository = _StubRepo(
        _CORPUS,
        direct={
            frozenset({"mtor", "naked mole-rat"}): 0,  # nobody has linked them -> OPEN
            frozenset({"autophagy", "proteostasis"}): 7,  # well covered -> KNOWN
        },
    )
    audited = SqliteKnowledgeBase(":memory:")
    trace = stages.run(
        "why do we age",
        formalizer=_StubFormalizer(NARROW),
        web=_StubWeb([]),
        extractor=_StubExtractor(_CONCEPTS),
        papers=repository,
        ranker=_StubRanker([("AMBC_1", 0.9), ("AMBC_2", 0.4)]),
        knowledge_base=audited,
    )
    return trace, audited


def test_full_run_produces_mixed_verdicts():
    trace, _ = _run()
    verdicts = {(c.pair.a.name, c.pair.c.name): c.verdict for c in trace.claims}
    assert verdicts[("mTOR", "naked mole-rat")] is NoveltyVerdict.OPEN
    assert verdicts[("autophagy", "proteostasis")] is NoveltyVerdict.KNOWN
    assert len(set(verdicts.values())) > 1, "a uniform verdict set is a bug, not a result"


def test_replay_reproduces_the_run():
    trace, _ = _run()
    replayed = RecordedRun(RunTrace.model_validate_json(trace.model_dump_json()))
    again = stages.run(
        trace.raw_question,
        formalizer=replayed,
        web=replayed,
        extractor=replayed,
        papers=replayed,
        ranker=replayed,
        knowledge_base=SqliteKnowledgeBase(":memory:"),
        run_id=trace.run_id,
    )

    def stable(payload):
        # A replay is a new run, so its step timestamps legitimately differ.
        for claim in payload["novel_claims"]:
            for step in claim["reasoning"]:
                step.pop("at")
        return payload["novel_claims"]

    assert output(again)["ranked_evidence"] == output(trace)["ranked_evidence"]
    assert stable(output(again)) == stable(output(trace))
    assert stable(output(trace)), "the replay comparison must not be vacuous"


def test_every_stage_leaves_a_trace_entry():
    trace, audited = _run()
    logged = audited.steps_for(question_id("why do we age"))
    assert [step.stage for step in logged] == ["formalize", "ground", "gather", "rank"]
    assert "mTOR" in next(s for s in logged if s.stage == "ground").rationale
    assert trace.graph_as_of, "the graph snapshot must be recorded for reproduction"
    # The archive must be self-contained: diffing two run files has to work
    # without the knowledge base being around.
    assert [s.stage for s in trace.trace_steps] == [s.stage for s in logged]
    assert output(trace)["reasoning_trace"], "the archived trail must not be empty"


# --- premises: L0 -> L3 -------------------------------------------------------

from backend.grounding import premises  # noqa: E402
from backend.grounding.adapters import Verification  # noqa: E402
from backend.grounding.domain import (  # noqa: E402
    Decomposition as _Decomposition,
    Evidence,
    PremiseStatus,
    Triple,
    premise_id,
)

_SIRT1 = Triple(subject="activating SIRT1", verb="improves", object="mitochondrial biogenesis")
_HEALTH = Triple(subject="mitochondrial biogenesis", verb="extends", object="human healthspan")
_PGC = Triple(subject="SIRT1", verb="deacetylates", object="PGC-1alpha")


class _StubTriplifier:
    def __init__(self, decomposition):
        self.decomposition = decomposition

    def triplify(self, raw):
        return self.decomposition


class _StubProber:
    def probe(self, triples):
        return [_PGC, _PGC]  # a duplicate, to be collapsed


class _StubLinkRepo:
    """Papers for the molecular links, nothing for the organismal one."""

    def find(self, query):
        if "healthspan" in query.text:
            return []
        return [Paper(amass_id="AMBC_9", title="SIRT1 deacetylates PGC-1alpha", pmid="999")]

    def count_direct(self, a, c):
        return 0


class _StubVerifier:
    def verify(self, link, papers):
        # PGC-1alpha papers are topical only: the verdict is UNVERIFIED even
        # though Claude "relied on" a paper, and that paper must not survive.
        status = PremiseStatus.UNVERIFIED if link.object == "PGC-1alpha" else PremiseStatus.ESTABLISHED
        return Verification(
            status=status, why="stub", evidence=[Evidence(amass_id="AMBC_9", pmid="999", how="knockout mouse")]
        )


def _ground(decomposition=None, knowledge_base=None):
    return premises.extract(
        "sirt1?",
        triplifier=_StubTriplifier(
            decomposition
            or _Decomposition(coherent=True, why="named cause and outcome", triples=[_SIRT1, _HEALTH])
        ),
        prober=_StubProber(),
        sources=[_StubLinkRepo(), _StubLinkRepo()],  # the same record from two sources counts once
        verifier=_StubVerifier(),
        knowledge_base=knowledge_base,
        run_id="r-premises",
    )


def test_premises_mixed_verdicts_and_unverified_gap_recorded():
    grounding = _ground()
    assert grounding.triples == [_SIRT1, _HEALTH]
    statuses = {p.statement: p.status for p in grounding.premises}
    assert len(grounding.premises) == 3, "the duplicate probe must collapse"
    assert statuses["activating SIRT1 improves mitochondrial biogenesis"] is PremiseStatus.ESTABLISHED
    assert statuses["mitochondrial biogenesis extends human healthspan"] is PremiseStatus.UNVERIFIED
    assert len(set(statuses.values())) > 1, "a uniform verdict set is a bug, not a result"
    gaps = {p.statement: p for p in grounding.unverified_premises}
    assert gaps["mitochondrial biogenesis extends human healthspan"].absence_checked == (
        "amass biomedcore+trialcore, 0 records for the pair"
    )
    assert gaps["SIRT1 deacetylates PGC-1alpha"].absence_checked == (
        "amass biomedcore+trialcore, 1 records for the pair, none verify the link"
    )
    assert all(gap.evidence == [] for gap in gaps.values()), "UNVERIFIED carries no evidence"
    assert "PMID:999" in grounding.knowledge_graph
    assert "Weakest links: mitochondrial biogenesis extends human healthspan; SIRT1 deacetylates PGC-1alpha" in grounding.knowledge_graph


def test_incoherent_question_yields_no_premises_and_a_reason():
    grounding = _ground(_Decomposition(coherent=False, why="no relation asserted"))
    assert not grounding.coherent
    assert grounding.premises == [] and grounding.unverified_premises == []
    assert grounding.why == "no relation asserted"


def test_l0_acceptance_fixture_is_a_via_chain_without_the_experiment_ask():
    """Explainability contract for the SIRT1 question — not a live Claude snapshot.

    'via' is two linked triples (object of the first is subject of the second).
    A request for the next experiment is a deliverable, not a premise.
    """
    assert _SIRT1.object == _HEALTH.subject
    blob = " ".join(f"{t.subject} {t.verb} {t.object}" for t in (_SIRT1, _HEALTH)).lower()
    assert "experiment" not in blob


def test_render_graph_is_the_human_readable_trace():
    graph = premises.render_graph(_ground().premises)
    assert "activating SIRT1 -improves-> mitochondrial biogenesis" in graph
    assert "mitochondrial biogenesis -extends-> human healthspan" in graph
    assert "ESTABLISHED" in graph and "UNVERIFIED" in graph
    assert "Weakest links:" in graph
    assert "PMID:999" in graph



def test_premises_are_persisted_with_their_verdict_history():
    knowledge_base = SqliteKnowledgeBase(":memory:")
    _ground(knowledge_base=knowledge_base)
    _ground(knowledge_base=knowledge_base)  # same question again: history appends, nodes do not duplicate
    node = premise_id(_SIRT1)
    assert [s.verdict for s in knowledge_base.steps_for(node)] == ["ESTABLISHED", "ESTABLISHED"]
    assert [s.stage for s in knowledge_base.steps_for(question_id("sirt1?"))] == [
        "triplify", "probe", "triplify", "probe"
    ]
    view = knowledge_base.describe()
    assert "Q sirt1?" in view
    assert "activating SIRT1 improves mitochondrial biogenesis  [ESTABLISHED]" in view
    assert "PMID:999  knockout mouse" in view
    assert "absence checked: amass biomedcore+trialcore, 0 records for the pair" in view
    assert "premise=3" in view and "question=1" in view


# --- hypotheses: the plug-in seam and the testability filter ------------------

from backend.grounding.domain import Hypothesis  # noqa: E402
from backend.grounding.hypotheses import select  # noqa: E402
from backend.grounding.hypotheses import testable as _testable  # noqa: E402  (pytest would collect the bare name)

_GAP = premise_id(_HEALTH)


def _hypothesis(statement, subject="mitochondrial biogenesis", obj="human healthspan", targets=_GAP, **extra):
    fields = dict(
        intervention="exercise", readout="frailty index", model_system="adults over 65",
        falsification="frailty index unchanged after 12 months",
    )
    fields.update(extra)
    return Hypothesis(subject=subject, verb="extends", object=obj, statement=statement, targets=targets, **fields)


class _StubGenerator:
    def generate(self, grounding):
        return [
            _hypothesis("Exercise-driven mitochondrial biogenesis extends human healthspan in older adults"),
            _hypothesis("PGC-1alpha overexpression-driven mitochondrial biogenesis extends human healthspan"),  # same link
            _hypothesis(
                "Even if SIRT1 activation improves biogenesis, this does not translate into healthspan gains "
                "within feasible trial timeframes"
            ),
            _hypothesis("mtDNA copy number extends human healthspan", subject="mtDNA copy number"),
            _hypothesis("mitochondrial biogenesis extends human healthspan", targets="E:nope"),
            _hypothesis("mitochondrial biogenesis extends human healthspan", targets=premise_id(_SIRT1)),
            _hypothesis("mitochondrial biogenesis extends human healthspan", readout=""),
            _hypothesis("mitochondrial biogenesis extends human healthspan", falsification=""),
        ]


def test_testability_filter_names_the_one_reason():
    grounding = _ground()
    assert _testable(_hypothesis("mitochondrial biogenesis extends human healthspan"), grounding) is None
    assert _testable(_hypothesis("a even if b"), grounding) == "compound claim"
    assert _testable(_hypothesis(" ".join(["w"] * 21)), grounding).startswith("statement longer than")
    assert "subject and object" in _testable(_hypothesis("x", subject="mtDNA copy number"), grounding)
    assert _testable(_hypothesis("x", targets="E:nope"), grounding) == "targets no known premise"
    assert _testable(_hypothesis("x", targets=premise_id(_SIRT1)), grounding) == "targets an established link"
    assert "missing intervention" in _testable(_hypothesis("x", readout=""), grounding)
    assert "falsification" in _testable(_hypothesis("x", falsification=""), grounding)


def test_select_keeps_one_hypothesis_per_weak_link_with_its_evidence_context():
    grounding = _ground()
    kept, dropped = select(_StubGenerator().generate(grounding), grounding)
    assert [h.id for h in kept] == ["H1"]
    assert kept[0].statement.startswith("Exercise-driven")
    # The established link upstream (SIRT1 -> biogenesis) is why the hypothesis exists;
    # the gap's recorded absence is what it is missing.
    assert kept[0].supported_by == [premise_id(_SIRT1)]
    assert kept[0].conflicts_with == []
    assert kept[0].missing == "amass biomedcore+trialcore, 0 records for the pair"
    assert [reason for _, reason in dropped] == [
        "second hypothesis for the same link",
        "compound claim",
        "does not keep the target link's subject and object",
        "targets no known premise",
        "targets an established link",
        "missing intervention, readout or model system",
        "missing falsification criterion",
    ]


def test_generator_plugs_into_extract_and_is_audited():
    knowledge_base = SqliteKnowledgeBase(":memory:")
    grounding = premises.extract(
        "sirt1?",
        triplifier=_StubTriplifier(
            _Decomposition(coherent=True, why="named cause and outcome", triples=[_SIRT1, _HEALTH])
        ),
        prober=_StubProber(),
        sources=[_StubLinkRepo()],
        verifier=_StubVerifier(),
        generator=_StubGenerator(),
        knowledge_base=knowledge_base,
        run_id="r-hyp",
    )
    assert [h.statement for h in grounding.hypotheses] == [
        "Exercise-driven mitochondrial biogenesis extends human healthspan in older adults"
    ]
    assert grounding.weak_premises[0].statement == "mitochondrial biogenesis extends human healthspan"
    view = knowledge_base.describe()
    assert "hypothesis: Exercise-driven mitochondrial biogenesis extends human healthspan in older adults" in view
    assert "do: exercise | measure: frailty index | in: adults over 65" in view
    assert "rejected if: frailty index unchanged after 12 months" in view
    [step] = [s for s in knowledge_base.steps_for(question_id("sirt1?")) if s.stage == "hypothesize"]
    assert step.verdict == "1 kept, 7 dropped"
    assert "compound claim" in step.rationale


def test_generator_target_reference_resolves_index_or_entity_names():
    from backend.grounding.adapters import resolve_target

    weak = {"P1": _ground().weak_premises[0]}  # mitochondrial biogenesis -> human healthspan
    assert resolve_target("P1", weak) is weak["P1"]
    assert resolve_target("p1", weak) is weak["P1"]
    assert resolve_target("1", weak) is weak["P1"]
    assert resolve_target("mitochondrial biogenesis -> human healthspan", weak) is weak["P1"]
    assert resolve_target("Mitochondrial Biogenesis extends Human Healthspan [UNVERIFIED]", weak) is weak["P1"]
    assert resolve_target("P7", weak) is None
    assert resolve_target("SIRT1 -> PGC-1alpha", weak) is None
