"""Grounding pipeline: pure logic, the knowledge base, and record/replay.

Offline — no network, no API keys. Stub ports stand in for Tavily, Amass and
Claude, and the knowledge base runs on `:memory:`.
"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.grounding import adapters, stages  # noqa: E402
from backend.grounding.adapters import (  # noqa: E402
    ClinicalTrialsRepository,
    PubMedPaperRepository,
    RecordedRun,
    _parse_fence,
)
from backend.grounding.domain import (  # noqa: E402
    BiologicalEntity,
    Decomposition,
    LiteratureQuery,
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
    Premise,
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
        # A duplicate and a re-verbed copy of an L0 link with arrow syntax in the
        # verb — both must collapse onto the links already present.
        return [_PGC, _PGC, Triple(subject="activating SIRT1", verb="-activation raises->", object="mitochondrial biogenesis")]


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
        "amass biomedcore+trialcore, 0 records over 2 searches"
    )
    assert gaps["SIRT1 deacetylates PGC-1alpha"].absence_checked == (
        "amass biomedcore+trialcore, 1 records over 2 searches, none verify the link"
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
    assert "absence checked: amass biomedcore+trialcore, 0 records over 2 searches" in view
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
    assert "humans" in _testable(_hypothesis("biogenesis extends healthspan in aged mice", model_system="aged mice"), grounding)


def test_triple_strips_arrow_syntax_from_fields():
    triple = Triple(subject=" SIRT1", verb="-activation improves->", object="mitochondrial biogenesis ")
    assert (triple.subject, triple.verb, triple.object) == ("SIRT1", "activation improves", "mitochondrial biogenesis")


def test_select_keeps_one_hypothesis_per_weak_link_with_its_evidence_context():
    grounding = _ground()
    kept, dropped = select(_StubGenerator().generate(grounding), grounding)
    assert [h.id for h in kept] == ["H1"]
    assert kept[0].statement.startswith("Exercise-driven")
    # The established link upstream (SIRT1 -> biogenesis) is why the hypothesis exists;
    # the gap's recorded absence is what it is missing.
    assert kept[0].supported_by == [premise_id(_SIRT1)]
    assert kept[0].conflicts_with == []
    assert kept[0].missing == "amass biomedcore+trialcore, 0 records over 2 searches"
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


# --- destination, measurability, second look, ledger, rejected audit ------------


def test_destination_restricts_hypotheses_to_links_ending_at_the_outcome():
    grounding = _ground(_Decomposition(
        coherent=True, why="cause, mechanism, outcome", triples=[_SIRT1, _HEALTH], destination="human healthspan",
    ))
    assert grounding.destination == "human healthspan"
    assert "Destination (the outcome asked about): human healthspan" in grounding.knowledge_graph
    # weak links: SIRT1->PGC-1alpha (UNVERIFIED via stub) and biogenesis->healthspan; only the latter ends at the destination
    assert [p.statement for p in grounding.weak_premises] == ["mitochondrial biogenesis extends human healthspan"]
    aimed_at_pgc = _hypothesis("SIRT1 deacetylates PGC-1alpha in human hepatocytes", subject="SIRT1", obj="PGC-1alpha", targets=premise_id(_PGC))
    assert _testable(aimed_at_pgc, grounding) == "does not end at the destination node (human healthspan)"
    assert _testable(_hypothesis("exercise-driven mitochondrial biogenesis extends human healthspan at 12 months"), grounding) is None


def test_vague_wording_is_not_measurable():
    grounding = _ground()
    assert _testable(_hypothesis("mitochondrial biogenesis extends human healthspan within weeks"), grounding) == "vague or unmeasurable wording"
    assert _testable(_hypothesis("mitochondrial biogenesis may extend human healthspan"), grounding) == "vague or unmeasurable wording"
    assert _testable(_hypothesis("mitochondrial biogenesis extends human healthspan at 12 months"), grounding) is None


def test_second_look_widens_the_query_before_calling_a_link_unverified():
    class _Repo:
        def __init__(self):
            self.queries = []

        def find(self, query):
            self.queries.append(query.text)
            # only the verb-bearing query finds the paper
            return [Paper(amass_id="AMBC_77", title="found on second look", pmid="777")] if "extends" in query.text else []

        def count_direct(self, a, c):
            return 0

    class _Verifier:
        def verify(self, link, papers):
            return Verification(status=PremiseStatus.ESTABLISHED, why="second look", evidence=[Evidence(amass_id="AMBC_77", pmid="777", how="RCT")])

    repo = _Repo()
    status, evidence, absence, why, _ = premises.activate(_HEALTH, [repo], _Verifier())
    assert repo.queries == [
        "mitochondrial biogenesis human healthspan",
        "mitochondrial biogenesis extends human healthspan",
        "mitochondrial biogenesis human healthspan randomized trial",
    ]
    assert status is PremiseStatus.ESTABLISHED and evidence[0].pmid == "777" and absence is None


def test_rejected_candidates_are_persisted_for_the_audit():
    knowledge_base = SqliteKnowledgeBase(":memory:")
    grounding = premises.extract(
        "sirt1?",
        triplifier=_StubTriplifier(_Decomposition(coherent=True, why="ok", triples=[_SIRT1, _HEALTH])),
        prober=_StubProber(), sources=[_StubLinkRepo()], verifier=_StubVerifier(),
        generator=_StubGenerator(), knowledge_base=knowledge_base, run_id="r-rej",
    )
    assert len(grounding.rejected) == 7 and all(h.dropped for h in grounding.rejected)
    view = knowledge_base.describe()
    assert "rejected hypothesis:" in view and "(compound claim)" in view
    from backend.kgviz.graph import load_graph
    graph = load_graph(knowledge_base.connection)
    rejected_nodes = [n for n in graph["nodes"] if n["kind"] == "hypothesis" and n["dropped"]]
    # One node per distinct rejected statement (four share the same sentence), each carrying its reason.
    assert len(rejected_nodes) == 4 and all(n["dropped"] for n in rejected_nodes)
    assert graph["nodes"][[n["kind"] for n in graph["nodes"]].index("question")]["destination"] == ""


def test_ledger_streams_every_external_call():
    from backend.grounding.adapters import Ledger

    seen = []
    ledger = Ledger(seen.append)
    ledger.append({"tool": "amass", "args": {"core": "biomedcore", "query": "q"}, "summary": "3 records", "usage": None, "cached": False})
    assert seen == list(ledger) and seen[0]["tool"] == "amass"


# --- a malformed citation must cost that citation, not the grounding ---------


def test_verdict_recovers_misspelled_citation_keys_and_drops_unusable_ones():
    from backend.grounding.adapters import _Verdict

    reply = """```json
{"status": "CONTESTED", "why": "trials conflict", "evidence": [
  {"amass_id": "AMBC_1", "how": "human RCT"},
  {"amba_id": "AMBC_2uvZxx7", "how": "review"},
  {"amassId": "AMTC_3", "how": "registered trial, no results"},
  {"how": "no id at all"},
  "not even a dict"
]}
```"""
    verdict = _parse_fence(reply, _Verdict)
    assert verdict.status is PremiseStatus.CONTESTED and verdict.why == "trials conflict"
    assert [e.amass_id for e in verdict.evidence] == ["AMBC_1", "AMBC_2uvZxx7", "AMTC_3"]


def test_parse_fence_turns_a_schema_violation_into_a_value_error():
    import pytest

    from backend.grounding.adapters import _Verdict

    with pytest.raises(ValueError, match="unparseable model reply"):
        _parse_fence('{"why": "status is missing"}', _Verdict)


class _FlakyVerifier(_StubVerifier):
    """Unparseable on the first call for a given link, fine afterwards."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls: dict[str, int] = {}

    def verify(self, link, papers):
        key = Premise.render(link)
        self.calls[key] = self.calls.get(key, 0) + 1
        if self.calls[key] <= self.fail_times:
            raise ValueError("unparseable model reply (evidence.2.amass_id missing)")
        return super().verify(link, papers)


def _ground_with(verifier, knowledge_base=None):
    return premises.extract(
        "sirt1?",
        triplifier=_StubTriplifier(_Decomposition(coherent=True, why="named cause and outcome", triples=[_SIRT1, _HEALTH])),
        prober=_StubProber(),
        sources=[_StubLinkRepo()],
        verifier=verifier,
        knowledge_base=knowledge_base,
        run_id="r-flaky",
    )


def test_one_unparseable_verdict_is_retried_and_the_grounding_completes():
    verifier = _FlakyVerifier(fail_times=1)
    grounding = _ground_with(verifier)
    assert grounding.coherent and len(grounding.premises) == 3
    statuses = {p.statement: p.status for p in grounding.premises}
    assert statuses["activating SIRT1 improves mitochondrial biogenesis"] is PremiseStatus.ESTABLISHED
    assert verifier.calls["activating SIRT1 improves mitochondrial biogenesis"] == 2


def test_a_link_that_never_parses_is_left_out_not_turned_into_a_gap():
    knowledge_base = SqliteKnowledgeBase(":memory:")
    grounding = _ground_with(_FlakyVerifier(fail_times=99), knowledge_base)
    assert grounding.coherent, "one bad link must not fail the whole grounding"
    statements = [p.statement for p in grounding.premises]
    # the two links with papers could not be judged and are absent; the one
    # with no literature never reached the verifier and is still UNVERIFIED
    assert statements == ["mitochondrial biogenesis extends human healthspan"]
    assert "activating SIRT1 improves mitochondrial biogenesis" not in grounding.knowledge_graph
    errors = [s for s in knowledge_base.steps_for(question_id("sirt1?")) if s.stage == "verify" and s.verdict == "error"]
    assert len(errors) == 2 and all("unparseable" in s.rationale for s in errors)


def test_every_link_failing_fails_loudly_instead_of_an_empty_graph():
    import pytest

    class _AlwaysPapers(_StubLinkRepo):
        def find(self, query):
            return [Paper(amass_id="AMBC_9", title="topical", pmid="999")]

    with pytest.raises(ValueError, match="no link could be verified"):
        premises.extract(
            "sirt1?",
            triplifier=_StubTriplifier(_Decomposition(coherent=True, why="ok", triples=[_SIRT1, _HEALTH])),
            prober=_StubProber(),
            sources=[_AlwaysPapers()],
            verifier=_FlakyVerifier(fail_times=99),
            run_id="r-all-fail",
        )


# --- misspelled keys anywhere in a reply cost the row, never the reply ---------


def test_proposals_recover_misspelled_keys_and_drop_hopeless_rows():
    from backend.grounding.adapters import _Proposals

    reply = """```json
{"hypotheses": [
  {"targets": "P1", "verb": "extends", "statement": "s1", "intervention": "i", "readout": "r",
   "model system": "older adults", "falsification_criterion": "no change at 12 months"},
  {"Targets": "P2", "verb": "extends", "statement": "s2", "intervention": "i", "readout": "r",
   "modelSystem": "human fibroblasts", "falsification": "f"},
  {"verb": "extends", "statement": "no target, no intervention"},
  42
]}
```"""
    proposals = _parse_fence(reply, _Proposals)
    assert [p.targets for p in proposals.hypotheses] == ["P1", "P2"]
    assert proposals.hypotheses[0].model_system == "older adults"
    assert proposals.hypotheses[0].falsification == "no change at 12 months"
    assert proposals.hypotheses[1].model_system == "human fibroblasts"


def test_triple_list_accepts_the_prompts_name_for_the_list_and_drops_broken_rows():
    from backend.grounding.adapters import _TripleList

    reply = '{"links": [{"Subject": "SIRT1", "verb": "deacetylates", "Object": "PGC-1alpha"}, {"subject": "x", "verb": "y"}]}'
    assert [(t.subject, t.object) for t in _parse_fence(reply, _TripleList).triples] == [("SIRT1", "PGC-1alpha")]
    assert _parse_fence('{"triples": "not a list"}', _TripleList).triples == []


def test_decomposition_drops_a_broken_triple_but_keeps_the_rest():
    reply = '{"coherent": true, "why": "ok", "triples": [{"subject": "A", "verb": "raises", "object": "B"}, {"subject": "A", "object": "C"}], "destination": "B"}'
    decomposition = _parse_fence(reply, _Decomposition)
    assert [t.object for t in decomposition.triples] == ["B"]


def test_claude_asks_once_more_when_the_first_reply_does_not_fit():
    from backend.agent.providers import LLMResponse
    from backend.grounding import adapters

    replies = iter(['```json\n{"why": "no status"}\n```', '```json\n{"status": "ESTABLISHED", "why": "fine", "evidence": []}\n```'])
    calls = []

    class _FakeProvider:
        model = "test-model"

        def complete(self, prompt, max_tokens):
            calls.append(prompt)
            return LLMResponse(text=next(replies))

    knowledge_base = SqliteKnowledgeBase(":memory:")
    verdict, digest = adapters._claude("judge this", adapters._Verdict, knowledge_base, stage="t", provider=_FakeProvider())
    assert verdict.status is PremiseStatus.ESTABLISHED and len(calls) == 2
    assert knowledge_base.cached_response(digest) is not None, "the reply that fit is what gets cached"


def test_an_unusable_probe_reply_falls_back_to_the_question_links():
    class _BrokenProber:
        def probe(self, triples):
            raise ValueError("unparseable model reply")

    knowledge_base = SqliteKnowledgeBase(":memory:")
    grounding = premises.extract(
        "sirt1?",
        triplifier=_StubTriplifier(_Decomposition(coherent=True, why="ok", triples=[_SIRT1, _HEALTH])),
        prober=_BrokenProber(),
        sources=[_StubLinkRepo()],
        verifier=_StubVerifier(),
        knowledge_base=knowledge_base,
        run_id="r-probe",
    )
    assert [p.statement for p in grounding.premises] == [Premise.render(_SIRT1), Premise.render(_HEALTH)]
    assert any(s.stage == "probe" and s.verdict == "error" for s in knowledge_base.steps_for(question_id("sirt1?")))


def test_a_failed_hypothesis_generator_still_hands_plan_the_premises():
    class _BrokenGenerator:
        def generate(self, grounding):
            raise ValueError("unparseable model reply")

    knowledge_base = SqliteKnowledgeBase(":memory:")
    grounding = premises.extract(
        "sirt1?",
        triplifier=_StubTriplifier(_Decomposition(coherent=True, why="ok", triples=[_SIRT1, _HEALTH])),
        prober=_StubProber(),
        sources=[_StubLinkRepo()],
        verifier=_StubVerifier(),
        generator=_BrokenGenerator(),
        knowledge_base=knowledge_base,
        run_id="r-gen",
    )
    assert grounding.coherent and len(grounding.premises) == 3
    assert grounding.hypotheses == [] and grounding.rejected == []
    assert "Weakest links:" in grounding.knowledge_graph
    assert any(s.stage == "hypothesize" and s.verdict == "error" for s in knowledge_base.steps_for(question_id("sirt1?")))


# --- keyless grounding fallback (PubMed / ClinicalTrials.gov, used when no
# AMASS_API_KEY is configured — Amass has no free tier) -----------------


class _FakeResponse:
    def __init__(self, json_data=None, text="", status_code=200):
        self._json = json_data
        self.text = text
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>111</PMID>
      <Article><Abstract><AbstractText>Abstract of paper one.</AbstractText></Abstract></Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">111</ArticleId>
        <ArticleId IdType="doi">10.1/one</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>222</PMID>
      <Article><Abstract><AbstractText>Abstract of paper two.</AbstractText></Abstract></Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_pubmed_paper_repository_finds_papers_with_abstracts(monkeypatch):
    esearch_payload = {"esearchresult": {"idlist": ["111", "222"]}}
    esummary_payload = {"result": {"111": {"title": "Paper One"}, "222": {"title": "Paper Two"}}}

    def fake_get(url, params=None, timeout=None):
        if url == adapters.PUBMED_ESEARCH_URL:
            return _FakeResponse(json_data=esearch_payload)
        if url == adapters.PUBMED_ESUMMARY_URL:
            return _FakeResponse(json_data=esummary_payload)
        if url == adapters.PUBMED_EFETCH_URL:
            return _FakeResponse(text=_EFETCH_XML)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(adapters.httpx, "get", fake_get)
    papers = PubMedPaperRepository().find(LiteratureQuery(text="SIRT1 aging"))
    assert [p.amass_id for p in papers] == ["PMID:111", "PMID:222"]
    assert papers[0].title == "Paper One"
    assert papers[0].abstract == "Abstract of paper one."
    assert papers[0].doi == "10.1/one"
    assert papers[0].pmid == "111"
    assert papers[1].abstract == "Abstract of paper two."


def test_pubmed_paper_repository_no_hits_returns_empty(monkeypatch):
    monkeypatch.setattr(
        adapters.httpx, "get", lambda url, params=None, timeout=None: _FakeResponse(json_data={"esearchresult": {"idlist": []}})
    )
    assert PubMedPaperRepository().find(LiteratureQuery(text="nonsense query")) == []


def test_ncbi_get_retries_once_on_429_then_succeeds(monkeypatch):
    # Reproduces the live bug report: a plain 429 with no retry aborted the
    # whole grounding run ("no link could be verified"). NCBI's rate limit
    # without a key is a "slow down", not a permanent failure.
    monkeypatch.setattr(adapters, "_ncbi_last_request_at", 0.0)
    monkeypatch.setattr(adapters.time, "sleep", lambda _seconds: None)
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResponse(status_code=429)
        return _FakeResponse(json_data={"esearchresult": {"idlist": ["1"]}}, status_code=200)

    monkeypatch.setattr(adapters.httpx, "get", fake_get)
    response = adapters._ncbi_get(adapters.PUBMED_ESEARCH_URL, {"db": "pubmed", "term": "x"})
    assert len(calls) == 2
    assert response.json()["esearchresult"]["idlist"] == ["1"]


def test_ncbi_get_raises_if_still_429_after_retry(monkeypatch):
    monkeypatch.setattr(adapters, "_ncbi_last_request_at", 0.0)
    monkeypatch.setattr(adapters.time, "sleep", lambda _seconds: None)

    class _Boom(_FakeResponse):
        def raise_for_status(self):
            raise httpx.HTTPStatusError("429", request=None, response=None)

    monkeypatch.setattr(adapters.httpx, "get", lambda url, params=None, timeout=None: _Boom(status_code=429))
    with pytest.raises(httpx.HTTPStatusError):
        adapters._ncbi_get(adapters.PUBMED_ESEARCH_URL, {"db": "pubmed", "term": "x"})


def test_pubmed_paper_repository_count_direct_reads_esearch_count(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        assert url == adapters.PUBMED_ESEARCH_URL
        assert params["retmax"] == 0
        return _FakeResponse(json_data={"esearchresult": {"count": "7"}})

    monkeypatch.setattr(adapters.httpx, "get", fake_get)
    assert PubMedPaperRepository().count_direct("SIRT1", "healthspan") == 7


_CT_STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT123", "briefTitle": "A Trial"},
        "statusModule": {"overallStatus": "RECRUITING"},
        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE2"]},
        "descriptionModule": {"briefSummary": "Summary text."},
        "armsInterventionsModule": {"interventions": [{"name": "Drug X"}]},
        "outcomesModule": {"primaryOutcomes": [{"measure": "Change in Y"}]},
    }
}


def test_clinicaltrials_repository_maps_study_fields(monkeypatch):
    monkeypatch.setattr(
        adapters.httpx, "get", lambda url, params=None, timeout=None: _FakeResponse(json_data={"studies": [_CT_STUDY]})
    )
    papers = ClinicalTrialsRepository().find(LiteratureQuery(text="SIRT1"))
    assert len(papers) == 1
    paper = papers[0]
    assert paper.amass_id == "NCT:NCT123"
    assert paper.nct_id == "NCT123"
    assert paper.title == "A Trial"
    assert "Summary text." in paper.abstract
    assert "Drug X" in paper.abstract
    assert "Change in Y" in paper.abstract
    assert paper.url == "https://clinicaltrials.gov/study/NCT123"


def test_clinicaltrials_repository_count_direct_reads_total_count(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        assert params["countTotal"] == "true"
        return _FakeResponse(json_data={"totalCount": 42, "studies": []})

    monkeypatch.setattr(adapters.httpx, "get", fake_get)
    assert ClinicalTrialsRepository().count_direct("A", "C") == 42
