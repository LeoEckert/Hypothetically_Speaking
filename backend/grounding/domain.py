"""Domain layer: models, ports and pure rules.

Nothing here touches the network, the filesystem or an API key. `adapters.py`
implements the ports, `stages.py` orchestrates them, `knowledge_base.py` stores
what they produce.

The novelty rule is Swanson's ABC model: if concept A and concept C are each
well connected to a bridging concept B, but no paper links A and C directly,
that absence is a candidate gap worth verifying against the literature.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

# --- tunables --------------------------------------------------------------

MAX_QUERIES = 5  # literature queries built from the stage 1 entities
MAX_GAP_CHECKS = 8  # concept pairs verified against Amass in stage 4
TOP_N = 10  # ranked papers that reach the output
SUPPORT_LIMIT = 5  # supporting papers attached to one claim

# TODO(bio): both thresholds are placeholders. Where EMERGING stops and KNOWN
# begins is a judgement about how much prior work counts as "already done",
# and that is a biological call, not a code one.
KNOWN_MIN_DIRECT = 5
MIN_BRIDGES = 2

# Humans steer the (not yet built) stage 6 loop by writing this file. The next
# round ingests it into `steps` and re-plans around the verdicts:
#   [{"claim_id": "K:0af2", "verdict": "KEEP|REFINE|DROP", "rationale": "..."}]
FEEDBACK_FILE = "feedback.json"


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


# --- models ----------------------------------------------------------------

EntityKind = Literal["gene", "pathway", "species"]


class ScientificQuestion(BaseModel):
    """Aggregate root. Stage 0 narrows a broad question onto four axes."""

    text: str
    mechanism: str | None = None
    cell_type: str | None = None
    endpoint: str | None = None
    time_horizon: str | None = None

    def is_narrow(self) -> bool:
        return all([self.mechanism, self.cell_type, self.endpoint, self.time_horizon])


class BiologicalEntity(BaseModel):
    name: str
    kind: EntityKind


class Triple(BaseModel):
    """One `A -verb-> B` premise lifted verbatim from the question (L0)."""

    subject: str
    verb: str
    object: str

    @field_validator("subject", "verb", "object")
    @classmethod
    def _plain(cls, value: str) -> str:
        # The model sometimes echoes the arrow syntax it was shown; a verb is words.
        return value.strip().strip("-<>→ ").strip()


class Decomposition(BaseModel):
    """L0 output. An incoherent question carries `why` and no triples."""

    coherent: bool
    why: str
    triples: list[Triple] = Field(default_factory=list)


class PremiseStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"  # literature verifies the link
    CONTESTED = "CONTESTED"  # literature exists and conflicts
    UNVERIFIED = "UNVERIFIED"  # nothing verifies it — the gaps to aim at


class Evidence(BaseModel):
    amass_id: str  # always present, so a record without PMID or NCT still has an identity
    pmid: str | None = None
    nct_id: str | None = None
    url: str | None = None
    how: str  # knockout mouse, human RCT, epidemiological association, ...

    def label(self) -> str:
        return f"PMID:{self.pmid}" if self.pmid else f"NCT:{self.nct_id}" if self.nct_id else self.amass_id


class Premise(Triple):
    """L3 output: the triple is canonical, `statement` is derived from it."""

    statement: str
    status: PremiseStatus
    evidence: list[Evidence] = Field(default_factory=list)
    absence_checked: str | None = None  # recorded query, so absence is not silence
    derived_from: str  # the L0 triple this link elaborates

    @classmethod
    def render(cls, triple: Triple) -> str:
        return f"{triple.subject} {triple.verb} {triple.object}"


class Hypothesis(Triple):
    """One interventional prediction aimed at one weak link.

    The frame is fixed: intervening on the link's subject will produce the
    link's object in a named model system, and here is what would falsify
    it. `subject`/`object` are the target premise's own; only the verb,
    wording, experiment and falsification are the generator's to choose.
    `supported_by` / `conflicts_with` / `missing` are computed from the
    graph, not written by the model — the "why this hypothesis exists" block.
    """

    id: str = ""
    statement: str
    targets: str  # premise_id of the weak link
    intervention: str  # what you would do to the subject
    readout: str  # what you would measure on the object
    model_system: str  # in whom or in what
    falsification: str  # the observation that would reject it
    rationale: str = ""
    supported_by: list[str] = Field(default_factory=list)  # ESTABLISHED premises adjacent in the chain
    conflicts_with: list[str] = Field(default_factory=list)  # CONTESTED premises adjacent in the chain
    missing: str | None = None  # the target's absence_checked, i.e. the gap itself


class Grounding(BaseModel):
    """What PLAN receives: every checked link, the unverified subset, and the
    hypotheses that survived the testability filter."""

    run_id: str = ""
    question: str
    coherent: bool
    why: str
    triples: list[Triple] = Field(default_factory=list)
    premises: list[Premise] = Field(default_factory=list)
    knowledge_graph: str = ""
    hypotheses: list[Hypothesis] = Field(default_factory=list)

    @property
    def weak_premises(self) -> list[Premise]:
        """What hypotheses should aim at: UNVERIFIED first, then CONTESTED."""
        order = {PremiseStatus.UNVERIFIED: 0, PremiseStatus.CONTESTED: 1}
        return sorted((p for p in self.premises if p.status in order), key=lambda p: order[p.status])

    @property
    def unverified_premises(self) -> list[Premise]:
        return [p for p in self.premises if p.status is PremiseStatus.UNVERIFIED]


class LiteratureQuery(BaseModel):
    text: str
    entity: BiologicalEntity | None = None


class WebSnippet(BaseModel):
    title: str
    url: str
    content: str
    score: float = 0.0


class Paper(BaseModel):
    """A publication or, with `nct_id`, a registered trial — same shape for the verifier."""

    amass_id: str
    title: str
    abstract: str | None = None
    doi: str | None = None
    pmid: str | None = None
    nct_id: str | None = None
    url: str | None = None
    citation_count: int | None = None
    mesh_terms: list[str] = Field(default_factory=list)


class RankedPaper(BaseModel):
    paper: Paper
    score: float
    rationale: str


class ReasoningStep(BaseModel):
    """One judgement about one node.

    Append-only: a step is never rewritten, so a node's history reads top to
    bottom — why it was proposed, what verification returned, what a critic
    said, what a human overrode.
    """

    node_id: str
    stage: str  # formalize | ground | gather | rank | novelty | critique | feedback
    verdict: str
    rationale: str
    run_id: str
    at: str  # UTC ISO 8601
    # sha256 of the prompt that produced this judgement, for LLM-backed stages.
    # Two runs that diverge are diffed on this: an equal hash with a different
    # outcome is a model problem, a different hash means the input changed.
    prompt_hash: str | None = None


class NoveltyVerdict(str, Enum):
    KNOWN = "KNOWN"  # established, drop it
    EMERGING = "EMERGING"  # somebody got there first
    OPEN = "OPEN"  # no direct literature, well bridged — the candidates
    UNSUPPORTED = "UNSUPPORTED"  # no direct literature and weak legs: noise


class ConceptPair(BaseModel):
    a: BiologicalEntity
    c: BiologicalEntity
    bridges: list[BiologicalEntity] = Field(default_factory=list)
    direct_papers: int | None = None  # None until stage 4 verifies


class NovelClaim(BaseModel):
    claim_id: str
    pair: ConceptPair
    verdict: NoveltyVerdict
    support: list[Paper] = Field(default_factory=list)
    reasoning: list[ReasoningStep] = Field(default_factory=list)


class RunTrace(BaseModel):
    """Every stage output of one run. Doubles as the capture/replay fixture."""

    run_id: str
    captured_at: str
    model: str = ""
    # Timestamp the co-occurrence graph was read at. Passing it back as
    # `graph_as_of` reconstructs this run's graph even after later runs have
    # added evidence — accumulation without losing reproducibility.
    graph_as_of: str = ""
    raw_question: str
    question: ScientificQuestion
    snippets: list[WebSnippet] = Field(default_factory=list)
    entities: list[BiologicalEntity] = Field(default_factory=list)
    queries: list[LiteratureQuery] = Field(default_factory=list)
    papers: list[Paper] = Field(default_factory=list)
    ranked: list[RankedPaper] = Field(default_factory=list)
    claims: list[NovelClaim] = Field(default_factory=list)
    # The per-stage trail, carried in the archive so two runs can be diffed
    # without querying the knowledge base.
    trace_steps: list[ReasoningStep] = Field(default_factory=list)


# --- node identity ---------------------------------------------------------


def concept_id(name: str) -> str:
    return "C:" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def paper_id(amass_id: str) -> str:
    return f"P:{amass_id}"


def question_id(raw: str) -> str:
    """The node every stage-0/1/3 judgement hangs off, stable across runs."""
    return "Q:" + hashlib.sha1(raw.strip().lower().encode()).hexdigest()[:8]


def prompt_hash(prompt: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()


def hypothesis_id(triple: Triple) -> str:
    return "H:" + "|".join(
        part.strip().lower() for part in (triple.subject, triple.verb, triple.object)
    )


def premise_id(triple: Triple) -> str:
    return "E:" + "|".join(
        part.strip().lower() for part in (triple.subject, triple.verb, triple.object)
    )


def claim_id(a: BiologicalEntity, c: BiologicalEntity) -> str:
    """Deterministic and order-independent, so a re-run addresses the same claim."""
    key = "|".join(sorted([concept_id(a.name), concept_id(c.name)]))
    return "K:" + hashlib.sha1(key.encode()).hexdigest()[:8]


# --- pure rules ------------------------------------------------------------


def queries_for(
    question: ScientificQuestion,
    entities: list[BiologicalEntity],
    limit: int = MAX_QUERIES,
) -> list[LiteratureQuery]:
    """Compose literature queries from grounded entities — deterministic, no LLM.

    The extractor's job is to report which entities the sources actually name.
    Turning those into search strings is mechanical, and therefore testable.
    """
    base = question.mechanism or question.text
    queries: list[LiteratureQuery] = []
    seen: set[str] = set()
    for entity in entities:
        text = f"{base} {entity.name}"
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        queries.append(LiteratureQuery(text=text, entity=entity))
        if len(queries) == limit:
            break
    return queries


def classify(direct_papers: int, bridges: int) -> NoveltyVerdict:
    if direct_papers >= KNOWN_MIN_DIRECT:
        return NoveltyVerdict.KNOWN
    if direct_papers > 0:
        return NoveltyVerdict.EMERGING
    if bridges >= MIN_BRIDGES:
        return NoveltyVerdict.OPEN
    return NoveltyVerdict.UNSUPPORTED


def mentions(paper: Paper, entity: BiologicalEntity) -> bool:
    # ponytail: plain substring match with no synonym or abbreviation
    # resolution ("mTOR" vs "mechanistic target of rapamycin"). Upgrade path is
    # an Amass GeneCore lookup per concept to canonicalise names before matching.
    needle = entity.name.lower()
    if any(needle in term.lower() for term in paper.mesh_terms):
        return True
    return needle in f"{paper.title} {paper.abstract or ''}".lower()


# --- ports -----------------------------------------------------------------


class QuestionFormalizer(Protocol):
    def formalize(self, raw: str) -> ScientificQuestion: ...


class WebSearchRepository(Protocol):
    def search(self, question: ScientificQuestion) -> list[WebSnippet]: ...


class EntityExtractor(Protocol):
    def extract(
        self, question: ScientificQuestion, snippets: list[WebSnippet]
    ) -> list[BiologicalEntity]: ...


class PaperRepository(Protocol):
    def find(self, query: LiteratureQuery) -> list[Paper]: ...

    # Separate from find() so a replay can return the recorded count instead of
    # fabricating papers for the caller to len().
    def count_direct(self, a: str, c: str) -> int: ...


class RelevanceRanker(Protocol):
    def rank(self, question: ScientificQuestion, papers: list[Paper]) -> list[RankedPaper]: ...


class LLMCache(Protocol):
    """Same prompt, same model, same answer — byte for byte.

    This is what turns "the reasoning should be similar" into "the reasoning is
    identical unless the input changed", and a cache miss is itself the signal
    that something upstream moved.
    """

    def cached_response(self, prompt_hash: str) -> str | None: ...
    def store_response(self, prompt_hash: str, model: str, response: str) -> None: ...


class KnowledgeBase(LLMCache, Protocol):
    def upsert_concept(self, entity: BiologicalEntity, run_id: str) -> str: ...
    def upsert_paper(self, paper: Paper, run_id: str) -> str: ...
    def link_mentions(self, paper_node: str, concept_node: str, run_id: str) -> None: ...

    # Append-only: one row per paper that witnessed the pair. Weight is derived
    # with COUNT(*), never overwritten, so the graph at any past moment can be
    # reconstructed and two runs can be diffed on the rows added between them.
    def observe_co_occurrence(
        self, paper_node: str, a_node: str, c_node: str, run_id: str
    ) -> None: ...

    def gap_candidates(
        self,
        limit: int = MAX_GAP_CHECKS,
        min_bridges: int = MIN_BRIDGES,
        as_of: str | None = None,
    ) -> list[ConceptPair]: ...
    def record_step(self, step: ReasoningStep) -> None: ...
    def steps_for(self, node_id: str) -> list[ReasoningStep]: ...
    def already_checked(self, node_id: str) -> bool: ...
