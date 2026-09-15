"""Infrastructure: the only layer that knows about HTTP, API keys and JSON shapes.

Live adapters call Tavily, Amass and Claude. `PubMedPaperRepository`/
`ClinicalTrialsRepository` are the keyless equivalents of the two Amass
repositories, used instead whenever no AMASS_API_KEY is configured (Amass has
no free tier — see scripts/run_grounding.py::ground() for the branch). Amass
stays the default when a key exists: curated, single-call, higher-quality
filtering. `RecordedRun` replays a captured `RunTrace` instead — one class
satisfies all five ports at once, because `Protocol` is structural.

Every HTTP call raises on a non-2xx. A 401 or 429 must fail the run loudly; an
empty list would read downstream as "no evidence exists", which is a lie.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.agent.env import env_str
from backend.grounding.domain import (
    TRIPLE_FIELDS,
    BiologicalEntity,
    Decomposition,
    Evidence,
    Grounding,
    Hypothesis,
    LiteratureQuery,
    LLMCache,
    Paper,
    RankedPaper,
    RunTrace,
    Premise,
    PremiseStatus,
    ScientificQuestion,
    Triple,
    WebSnippet,
    keep_valid_items,
    premise_id,
    prompt_hash,
)

MODEL = env_str("ANTHROPIC_MODEL", "claude-sonnet-5")
# Tried and rejected: Haiku for the L2 verdicts. On the same records it called
# every link ESTABLISHED, including "mitochondrial biogenesis extends human
# healthspan", which Sonnet consistently and correctly leaves UNVERIFIED — and
# with no weak link there is nothing to hypothesize about. The verdict is the
# trust-bearing judgement, so it stays on the main model. Haiku takes the L1
# probe (a creative elaboration step where a miss costs little); fast mode
# saves the rest by reading fewer, shorter records.
FAST_MODEL = env_str("GROUNDING_FAST_MODEL", "claude-haiku-4-5-20251001")
PROBE_MODEL = env_str("GROUNDING_PROBE_MODEL", FAST_MODEL)
VERIFY_MODEL = env_str("GROUNDING_VERIFY_MODEL", MODEL)
# Depths below are sized for a hard 300s-per-run external platform ceiling
# (Vercel Fluid Compute), scaled down from earlier, VM-era values pending
# empirical retuning against real timed runs (see scripts/run_demo.py).
ABSTRACT_CHARS_FAST = 1000
TRIAL_LIMIT_FAST = 6
MAX_TOKENS = 4096  # a verdict over 20 full abstracts needs the room
TAVILY_URL = "https://api.tavily.com/search"
AMASS_URL = "https://api.amass.tech/api/v1/cores/biomedcore/records"
AMASS_TRIALS_URL = "https://api.amass.tech/api/v1/cores/trialcore/records"
FIXTURE_PATH = Path("fixtures/recorded_run.json")

TAVILY_MAX_RESULTS = 10
AMASS_LIMIT = 12  # per query; the API allows up to 300

# Keyless fallback sources, used instead of Amass when no AMASS_API_KEY (BYOK
# or platform) is configured — Amass has no free tier, so requiring it would
# block every user who only has a free LLM key. Same NCBI/ClinicalTrials.gov
# endpoints backend/tools/pubmed_tool.py and clinicaltrials_tool.py already
# call, but grounding also needs real abstract text (for ClaudeVerifier's
# verdict), which those tools don't fetch.
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
CLINICALTRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"
KEYLESS_LIMIT = 12  # mirrors AMASS_LIMIT
# A citation floor only passes old work: the 2026 Nature Metabolism review on
# mitochondrial quality control has citationCount 0, and a floor of 5 deletes it.
MIN_CITATIONS = 0
# JUFO journal tier: 0 unrated (incl. preprints), 1 listed, 2 leading, 3 top.
MIN_JUFO = 1
MIN_PUBLICATION_DATE = "2010-01-01"
ABSTRACT_CHARS = 1800  # was the whole abstract (3000) pre-300s-cap; still most of it
HTTP_TIMEOUT = 60


_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*\})\s*```", re.DOTALL)


def _parse_fence(text: str, schema: type[BaseModel]) -> BaseModel:
    """Pull the fenced JSON object out of a reply and validate it.

    Same fenced-block convention as `backend/agent/loop.py`, rather than
    tool-use structured output — one parser style across the repo.
    """
    match = _JSON_FENCE_RE.search(text)
    if match:
        payload = match.group(1)
    else:
        # Unclosed fence or prose around the object: take the outermost braces.
        start, end = text.find("{"), text.rfind("}")
        payload = text[start : end + 1] if start != -1 and end > start else text.strip()
    try:
        return schema.model_validate(json.loads(payload))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"unparseable model reply ({exc}): {text[:300]!r}") from exc


class Ledger(list):
    """Every external call the grounding makes, as it happens: {"tool", "args",
    "summary", "usage", "cached"}. A list, so it is trivially thread-safe for
    append, with an optional callback so the caller can stream it live."""

    def __init__(self, on_append=None) -> None:
        super().__init__()
        self.on_append = on_append

    def append(self, entry: dict) -> None:  # type: ignore[override]
        super().append(entry)
        if self.on_append is not None:
            self.on_append(entry)


def _claude(
    prompt: str, schema: type[BaseModel], cache: LLMCache | None = None, ledger: Ledger | None = None, stage: str = "",
    provider=None,
) -> tuple[BaseModel, str]:
    """The single LLM entry point. `provider` is a
    backend.agent.providers.LLMProvider (Anthropic when a key is supplied,
    otherwise OpenRouter — every key here is BYOK, resolved once per
    `ground()` call via backend.agent.providers.get_provider).

    Returns the parsed object and the prompt hash. With a cache attached, an
    identical prompt replays the stored response byte for byte, so two runs over
    the same evidence produce the same reasoning rather than merely similar
    reasoning. A miss means the input genuinely changed, and the hash recorded
    in the reasoning log is what shows where.
    """
    model_label = provider.model
    instructed = (
        f"{prompt}\n\nRespond with ONLY a fenced ```json code block, no prose "
        f"before or after it, matching this JSON schema:\n"
        f"{json.dumps(schema.model_json_schema())}"
    )
    digest = prompt_hash(instructed, model_label)
    if cache is not None:
        stored = cache.cached_response(digest)
        if stored is not None:
            if ledger is not None:
                ledger.append({"tool": "grounding", "args": {"stage": stage, "model": model_label}, "summary": "cache hit — identical prompt replayed", "usage": None, "cached": True})
            return schema.model_validate_json(stored), digest

    def ask():
        response = provider.complete(instructed, MAX_TOKENS)
        return response, _parse_fence(response.text, schema)

    try:
        response, result = ask()
    except ValueError as exc:
        # A reply that does not fit the schema is a bad sample, not a bad
        # prompt; one fresh answer usually fits. Nothing was cached, so this
        # is a genuine re-ask.
        print(f"grounding {stage or model_label}: unparseable reply, asking once more ({str(exc)[:160]})", file=sys.stderr)
        response, result = ask()

    if cache is not None:
        cache.store_response(digest, model_label, result.model_dump_json())
    if ledger is not None:
        ledger.append({
            "tool": "grounding",
            "args": {"stage": stage, "model": model_label},
            # The parsed object, not the raw fenced reply: the trace should read
            # like a result ({"status": "CONTESTED", ...}), not like a transcript.
            "summary": result.model_dump_json()[:300],
            "usage": response.usage,
            "cached": False,
        })
    return result, digest


class _CachingAdapter:
    """Shared constructor: every LLM-backed adapter records its last prompt hash."""

    stage = ""

    def __init__(self, cache: LLMCache | None = None, ledger: Ledger | None = None, provider=None) -> None:
        self.cache = cache
        self.ledger = ledger
        if provider is None:
            from backend.agent.providers import get_provider

            provider = get_provider()
        self.provider = provider
        self.model = provider.model  # kept for callers that still read .model directly
        self.last_prompt_hash: str | None = None

    def _call(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        result, self.last_prompt_hash = _claude(prompt, schema, self.cache, self.ledger, self.stage, self.provider)
        return result


# --- structured-output DTOs ------------------------------------------------
# These exist only because structured output needs a top-level object: a bare
# list cannot be returned, and the ranker must not echo abstracts back at us.


class _EntityList(BaseModel):
    entities: list[BiologicalEntity] = Field(default_factory=list)


class _ScoredId(BaseModel):
    amass_id: str
    score: float
    rationale: str


class _Ranking(BaseModel):
    papers: list[_ScoredId] = Field(default_factory=list)


class _TripleList(BaseModel):
    triples: list[Triple] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _repair_triples(cls, data):
        if isinstance(data, dict):
            # The list sometimes arrives under the name the prompt used for it.
            raw = data.get("triples", data.get("links", data.get("premises")))
            data = {**data, "triples": keep_valid_items(raw, TRIPLE_FIELDS)}
        return data


_AMASS_ID_ALIASES = ("amass_id", "amassId", "amba_id", "amassid", "record_id", "id")
_AMASS_ID_RE = re.compile(r"^AM[A-Z]{2}_\w+$")


def _amass_id_of(item: dict) -> str | None:
    """The model sometimes misspells the key it was shown ('amba_id',
    'amassId'); the value is still the record id it was given, so recover it
    by any of the usual names, else by shape."""
    for key in _AMASS_ID_ALIASES:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in item.values():
        if isinstance(value, str) and _AMASS_ID_RE.match(value.strip()):
            return value.strip()
    return None


class _CitedHow(BaseModel):
    amass_id: str
    how: str

    @model_validator(mode="before")
    @classmethod
    def _recover_id(cls, data):
        if isinstance(data, dict) and not data.get("amass_id"):
            recovered = _amass_id_of(data)
            if recovered:
                data = {**data, "amass_id": recovered}
        return data


class _Verdict(BaseModel):
    status: PremiseStatus
    why: str
    evidence: list[_CitedHow] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _drop_unusable_citations(cls, data):
        # One malformed citation must cost that citation, not the whole
        # verdict — the status and rationale are still worth keeping.
        if isinstance(data, dict):
            raw = data.get("evidence")
            items = raw if isinstance(raw, list) else []
            data = {**data, "evidence": [e for e in items if isinstance(e, dict) and _amass_id_of(e)]}
        return data


class Verification(BaseModel):
    status: PremiseStatus
    why: str
    evidence: list[Evidence] = Field(default_factory=list)
    prompt_hash: str | None = None


class _Proposed(BaseModel):
    targets: str  # "P3" — index into the weak-link list shown in the prompt
    verb: str
    statement: str
    intervention: str
    readout: str
    model_system: str
    falsification: str
    rationale: str = ""


_PROPOSED_FIELDS = ("targets", "verb", "statement", "intervention", "readout", "model_system", "falsification")


class _Proposals(BaseModel):
    hypotheses: list[_Proposed] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _repair_proposals(cls, data):
        if isinstance(data, dict):
            data = {**data, "hypotheses": keep_valid_items(data.get("hypotheses"), _PROPOSED_FIELDS)}
        return data


# --- live adapters ---------------------------------------------------------


class ClaudeTriplifier(_CachingAdapter):
    """L0. Coherence check, then `A -verb-> B` triples with nothing added."""

    stage = "L0 split"

    def triplify(self, raw: str) -> Decomposition:
        return self._call(
            "You decompose a longevity research question into its stated premises.\n\n"
            f"Question:\n{raw}\n\n"
            "First decide whether this is a coherent scientific question: a named "
            "intervention or cause, a named mechanism or outcome, and a relation "
            "between them. If it is not, set coherent=false, explain in `why`, and "
            "return no triples.\n"
            "If it is, list every causal or mechanistic claim the question itself "
            "asserts or presupposes as `subject -verb-> object` triples. Use only "
            "entities and verbs present or directly implied in the question; do not "
            "add intermediaries, background knowledge, or hedges. A request for an "
            "experiment or a deliverable is not a premise — leave it out.\n"
            "Subject and object are bare canonical entity names — 'SIRT1', "
            "'mitochondrial biogenesis', 'human healthspan' — never 'activating SIRT1' "
            "or 'improved mitochondrial biogenesis'. Put the intervention or change into "
            "the verb instead: 'activation improves', 'increase extends'. Reuse the exact "
            "same spelling for an entity every time it appears.\n"
            "`destination` is the outcome the question ultimately asks about — its "
            "dependent variable (here that would be the entity whose change the asker "
            "cares about, e.g. 'human healthspan'), copied exactly from one triple's object.",
            Decomposition,
        )


class ClaudeProber(_CachingAdapter):
    """L1. Elaborates the chain from internal knowledge only — probes, not output."""

    stage = "L1 probe"

    def probe(self, triples: list[Triple]) -> list[Triple]:
        chain = "\n".join(f"{t.subject} -{t.verb}-> {t.object}" for t in triples)
        result = self._call(
            "You are a biologist reading the premises of a longevity research question.\n\n"
            f"Premises:\n{chain}\n\n"
            "Rewrite each premise as the chain of mechanistic links a biologist would "
            "expect to sit between subject and object, naming the intermediaries "
            "(proteins, processes, phenotypes). Use canonical entity names — 'SIRT1', "
            "'PGC-1alpha', 'mitochondrial biogenesis' — not phrases like 'activating "
            "SIRT1'. Use no sources: these are guesses to be looked up, not claims. "
            "Return only links, each as one subject -verb-> object triple, keeping the "
            "original links as well so the chain stays connected.",
            _TripleList,
        )
        return result.triples


class ClaudeVerifier(_CachingAdapter):
    """L2. Reads the papers a link retrieved and says whether they verify it, and how."""

    stage = "L2 verify"

    def __init__(self, cache: LLMCache | None = None, ledger: Ledger | None = None, provider=None,
                 abstract_chars: int = ABSTRACT_CHARS) -> None:
        super().__init__(cache, ledger, provider)
        self.abstract_chars = abstract_chars

    def verify(self, link: Triple, papers: list[Paper]) -> Verification:
        by_id = {paper.amass_id: paper for paper in papers}
        candidates = "\n\n".join(
            f"{paper.amass_id}\n{paper.title}\n{(paper.abstract or '')[:self.abstract_chars]}"
            for paper in papers
        )
        # _claude directly, not _call: verify() runs in a thread pool and the
        # shared last_prompt_hash would race. The hash travels with the result.
        verdict, digest = _claude(
            "You judge whether published literature and registered trials verify one "
            "mechanistic link.\n\n"
            f"Link: {link.subject} -{link.verb}-> {link.object}\n\n"
            f"Retrieved records (AMBC = publication, AMTC = registered trial):\n{candidates}\n\n"
            "ESTABLISHED if the papers directly demonstrate the link; CONTESTED if "
            "papers directly address it and conflict; UNVERIFIED if none of them "
            "actually test the link, however topical. For each paper you rely on, "
            "record its exact ID and how it verified the link — knockout mouse, human "
            "RCT (with status and whether results exist), epidemiological association, "
            "in vitro, review. A registered trial without results verifies nothing but "
            "shows the link is being tested. Cite only IDs given.",
            _Verdict,
            self.cache,
            self.ledger,
            f"L2 verify: {link.subject} -> {link.object}",
            self.provider,
        )
        return Verification(
            status=verdict.status,
            why=verdict.why,
            prompt_hash=digest,
            evidence=[
                Evidence(
                    amass_id=cited.amass_id,
                    pmid=by_id[cited.amass_id].pmid,
                    nct_id=by_id[cited.amass_id].nct_id,
                    url=_paper_url(by_id[cited.amass_id]),
                    how=cited.how,
                )
                for cited in verdict.evidence
                if cited.amass_id in by_id
            ],
        )


class ClaudeHypothesisGenerator(_CachingAdapter):
    """Our HypothesisGenerator. One claim per hypothesis, in the graph's own terms."""

    stage = "L4 hypothesize"

    def generate(self, grounding: Grounding) -> list[Hypothesis]:
        weak = grounding.weak_premises
        if not weak:
            return []
        by_index = {f"P{i}": p for i, p in enumerate(weak, start=1)}
        listed = "\n".join(
            f"P{i}: {p.subject} -{p.verb}-> {p.object}  [{p.status.value}"
            + (f"; {p.absence_checked}" if p.absence_checked else "")
            + "]"
            for i, p in enumerate(weak, start=1)
        )
        proposals = self._call(
            "You turn the weakest link of a grounded causal chain into one testable "
            "hypothesis. There is deliberately little creative room: the hypothesis IS "
            "the link, restated as an interventional prediction.\n\n"
            f"Knowledge graph (ESTABLISHED links are settled; do not re-hypothesize them):\n"
            f"{grounding.knowledge_graph}\n\n"
            + (f"Destination — the outcome the question asks about: {grounding.destination}. "
               "Every hypothesis must end there.\n\n" if grounding.destination else "")
            + f"Weak links, one hypothesis each:\n{listed}\n\n"
            "For every P-index write exactly one hypothesis in this frame: intervening on "
            "the link's SUBJECT will produce the link's OBJECT in a named model system. "
            "Keep the subject and object exactly as written in the link; choose only the "
            "verb, the intervention (what you do to the subject), the readout (how you "
            "measure the object), the model system (which humans, animals or cells), and "
            "the falsification criterion (the observation that would reject it — a null "
            "readout, or the readout improving while a harm appears). `statement` is at "
            "most 20 words, one claim, no 'and', 'but', 'even if' or semicolons, and it "
            "must be measurable: name the readout or its validated proxy, never vague "
            "timing like 'within weeks' or 'over time' — if time matters, state the "
            "horizon exactly ('at 12 months'). Prefer the model system in which the "
            "readout is obtainable within two years; when the link names humans, the "
            "model system must be human (cells, tissue or trial participants), not mice "
            "or worms. "
            "`targets` is the P-index exactly as listed, e.g. \"P2\".",
            _Proposals,
        )
        hypotheses = []
        for p in proposals.hypotheses:
            target = resolve_target(p.targets, by_index)
            hypotheses.append(
                Hypothesis(
                    # An unresolved target keeps the raw text so select() drops
                    # it visibly ("targets no known premise") instead of silently.
                    subject=target.subject if target else "?", verb=p.verb,
                    object=target.object if target else "?", statement=p.statement,
                    targets=premise_id(target) if target else p.targets,
                    intervention=p.intervention, readout=p.readout, model_system=p.model_system,
                    falsification=p.falsification, rationale=p.rationale,
                )
            )
        return hypotheses


def resolve_target(reference: str, by_index: dict[str, "Premise"]) -> "Premise | None":
    """Map the model's `targets` back to a weak link: "P2" first, else a string
    naming both ends of the link ("mitochondrial biogenesis -> human healthspan")."""
    match = re.search(r"\b[Pp]?(\d+)\b", reference)
    if match and (premise := by_index.get(f"P{match.group(1)}")):
        return premise
    lowered = reference.lower()
    for premise in by_index.values():
        if premise.subject.lower() in lowered and premise.object.lower() in lowered:
            return premise
    return None


def _paper_url(paper: Paper) -> str | None:
    if paper.url:
        return paper.url
    if paper.pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/"
    if paper.doi:
        return f"https://doi.org/{paper.doi}"
    return None


class ClaudeQuestionFormalizer(_CachingAdapter):
    """Stage 0. Narrows a broad question onto the four axes of ScientificQuestion."""

    def formalize(self, raw: str) -> ScientificQuestion:
        question = self._call(
            "You turn a broad longevity research question into a specific, testable one.\n\n"
            f"Question:\n{raw}\n\n"
            "Restate it constrained to a single mechanism, a single cell type, one "
            "measurable endpoint and one time horizon. Keep 'text' as the original "
            "question, verbatim. Leave a field null only if the question genuinely "
            "cannot be narrowed on that axis without inventing something.",
            ScientificQuestion,
        )
        return question.model_copy(update={"text": raw})


class TavilyWebSearch:
    """Stage 1. The question goes to Tavily as natural language, verbatim."""

    def search(self, question: ScientificQuestion) -> list[WebSnippet]:
        response = httpx.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
            json={
                "query": question.text,
                "max_results": TAVILY_MAX_RESULTS,
                "search_depth": "advanced",
                "include_raw_content": False,
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return [
            WebSnippet(
                title=result.get("title", ""),
                url=result.get("url", ""),
                content=result.get("content", ""),
                score=result.get("score", 0.0),
            )
            for result in response.json()["results"]
        ]


class ClaudeEntityExtractor(_CachingAdapter):
    """Stage 1. Reports only entities the sources actually name."""

    def extract(
        self, question: ScientificQuestion, snippets: list[WebSnippet]
    ) -> list[BiologicalEntity]:
        sources = "\n\n".join(f"{snippet.title}\n{snippet.content}" for snippet in snippets)
        result = self._call(
            "You ground a longevity research question in concrete biological entities.\n\n"
            f"Question:\n{question.text}\n"
            f"Mechanism of interest: {question.mechanism or 'unspecified'}\n\n"
            f"Web sources:\n{sources}\n\n"
            "List the genes, pathways and species these sources actually name that bear "
            "on the question. Use the canonical name for each. Do not invent entities "
            "the sources do not mention.",
            _EntityList,
        )
        return result.entities


def _amass_records(
    url: str, params: dict, cache: LLMCache | None, ledger: Ledger | None = None, api_key: str | None = None
) -> list[dict]:
    """GET one Amass core. With a cache, an identical query replays the recorded
    records, so a repeated question is verified against the same literature —
    the retrieval half of reproducibility, next to the LLM cache."""
    core = url.rsplit("/cores/", 1)[-1].split("/", 1)[0]
    key = prompt_hash(f"{url}?{json.dumps(params, sort_keys=True)}", "amass")
    if cache is not None and (stored := cache.cached_response(key)) is not None:
        records = json.loads(stored)
        if ledger is not None:
            ledger.append({"tool": "amass", "args": {"core": core, "query": params["query"]}, "summary": f"cache hit — {len(records)} records replayed", "usage": None, "cached": True})
        return records
    # ponytail: one retry, no backoff. Amass allows 60 req/60s and one run
    # makes a handful; a single slow read must not fail the whole grounding.
    for attempt in (1, 2):
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"Bearer {api_key or os.environ['AMASS_API_KEY']}"},
                params=params,
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            break
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == 2:
                raise
    # `data` is an array, not {"records": [...]}. The Amass product page
    # says otherwise but is stale; the OpenAPI spec and a live-verified
    # client agree on the array.
    records = response.json().get("data", [])
    if cache is not None:
        cache.store_response(key, "amass", json.dumps(records))
    if ledger is not None:
        ledger.append({"tool": "amass", "args": {"core": core, "query": params["query"]}, "summary": f"{len(records)} records", "usage": None, "cached": False})
    return records


class AmassTrialRepository:
    """L2, second source. Registered trials — the only place a human RCT shows up."""

    def __init__(
        self, cache: LLMCache | None = None, ledger: Ledger | None = None, limit: int = AMASS_LIMIT,
        api_key: str | None = None,
    ) -> None:
        self.cache = cache
        self.ledger = ledger
        self.limit = limit
        self.api_key = api_key

    def find(self, query: LiteratureQuery) -> list[Paper]:
        records = _amass_records(
            AMASS_TRIALS_URL, {"query": query.text, "limit": self.limit}, self.cache, self.ledger, self.api_key
        )
        return [
            Paper(
                amass_id=record["amassId"],
                title=record.get("briefTitle") or record.get("officialTitle") or "",
                abstract=(
                    f"{record.get('briefSummary') or ''}\n"
                    f"type: {record.get('studyType')}; phase: {record.get('phase')}; "
                    f"status: {record.get('overallStatus')}; results posted: {record.get('hasResults')}; "
                    f"enrollment: {record.get('enrollment')}\n"
                    f"interventions: {record.get('interventionNames')}\n"
                    f"primary outcomes: {record.get('primaryOutcomeMeasures')}"
                ),
                nct_id=record.get("nctId") or record.get("registryId"),
                url=record.get("sourceUrl"),
            )
            for record in records
        ]

    def count_direct(self, a: str, c: str) -> int:
        return len(self.find(LiteratureQuery(text=f'"{a}" "{c}"')))


class AmassPaperRepository:
    """Stage 2 and 4, and L2. Amass BiomedCore, filtered server-side."""

    def __init__(self, cache: LLMCache | None = None, ledger: Ledger | None = None, api_key: str | None = None) -> None:
        self.cache = cache
        self.ledger = ledger
        self.api_key = api_key

    def find(self, query: LiteratureQuery) -> list[Paper]:
        records = _amass_records(
            AMASS_URL,
            {
                "query": query.text,
                "limit": AMASS_LIMIT,
                "minCitationCount": MIN_CITATIONS,
                "minJournalQualityJufo": MIN_JUFO,
                "minPublicationDate": MIN_PUBLICATION_DATE,
                "isRetracted": "false",
            },
            self.cache,
            self.ledger,
            self.api_key,
        )
        return [
            Paper(
                amass_id=record["amassId"],
                title=record.get("title", ""),
                abstract=record.get("abstract"),
                doi=record.get("doi"),
                pmid=record.get("pmid"),
                citation_count=record.get("citationCount"),
                mesh_terms=record.get("meshTerms") or [],
            )
            for record in records
        ]

    def count_direct(self, a: str, c: str) -> int:
        """How many papers cover both concepts at once — the novelty measurement."""
        return len(self.find(LiteratureQuery(text=f'"{a}" "{c}"')))


# NCBI's E-utilities rate-limit fairly aggressively without an API key (3
# req/s) — and grounding's L2 verification runs one thread per link, each
# needing up to 3 of these calls (esearch/esummary/efetch), so concurrent
# links can trivially burst past that limit even though each individual
# caller is well-behaved. A global lock + minimum spacing serializes every
# eutils.ncbi.nlm.nih.gov call across all threads in this process; a 429
# that still gets through gets one Retry-After-respecting retry — same
# "slow down, not broken" policy as backend/tools/pubmed_tool.py's own
# tool-call path, just also closing the concurrency gap that path doesn't
# have (a single tool call there is never run in parallel with itself).
_ncbi_lock = threading.Lock()
_ncbi_last_request_at = 0.0
_NCBI_MIN_INTERVAL = 0.34


def _ncbi_get(url: str, params: dict) -> httpx.Response:
    global _ncbi_last_request_at
    with _ncbi_lock:
        wait = _NCBI_MIN_INTERVAL - (time.monotonic() - _ncbi_last_request_at)
        if wait > 0:
            time.sleep(wait)
        response = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
        _ncbi_last_request_at = time.monotonic()
    if response.status_code == 429:
        time.sleep(float(response.headers.get("Retry-After", 1)))
        with _ncbi_lock:
            response = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
            _ncbi_last_request_at = time.monotonic()
    response.raise_for_status()
    return response


def _get_with_retry(url: str, params: dict) -> httpx.Response:
    """Same one-retry-on-429 policy as _ncbi_get, without the cross-thread
    throttle — used for ClinicalTrials.gov, which hasn't been observed to
    need it as aggressively as NCBI does."""
    response = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
    if response.status_code == 429:
        time.sleep(float(response.headers.get("Retry-After", 1)))
        response = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response


def _pubmed_efetch_abstracts(pmids: list[str]) -> dict[str, dict]:
    """GET efetch for a batch of PMIDs at once, returning {pmid: {"abstract",
    "doi"}} — XML, not the plain-text rendering, because the text format
    interleaves multiple records with no reliable per-record delimiter to
    split back apart; the XML tree pairs each PMID with its own abstract."""
    if not pmids:
        return {}
    response = _ncbi_get(
        PUBMED_EFETCH_URL,
        {"db": "pubmed", "id": ",".join(pmids), "rettype": "abstract", "retmode": "xml"},
    )
    root = ET.fromstring(response.text)
    found: dict[str, dict] = {}
    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        abstract = "\n".join(
            "".join(node.itertext()) for node in article.findall(".//Abstract/AbstractText")
        )
        doi = next(
            (aid.text for aid in article.findall(".//ArticleIdList/ArticleId") if aid.get("IdType") == "doi"),
            None,
        )
        found[pmid_el.text] = {"abstract": abstract or None, "doi": doi}
    return found


class PubMedPaperRepository:
    """Keyless fallback for AmassPaperRepository: NCBI E-utilities. Same
    PaperRepository port, same "raise on failure, never fabricate" rule as
    the Amass adapters — a rate-limited or unreachable NCBI must fail the
    run loudly, not silently substitute an empty list."""

    def __init__(self, limit: int = KEYLESS_LIMIT) -> None:
        self.limit = limit

    def find(self, query: LiteratureQuery) -> list[Paper]:
        search = _ncbi_get(
            PUBMED_ESEARCH_URL,
            {"db": "pubmed", "term": query.text, "retmode": "json", "retmax": self.limit},
        )
        pmids = search.json().get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []
        summary = _ncbi_get(
            PUBMED_ESUMMARY_URL,
            {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"},
        )
        docs = summary.json().get("result", {})
        extra = _pubmed_efetch_abstracts(pmids)
        return [
            Paper(
                # PMID:-prefixed, matching this app's existing citation-id
                # convention (Evidence.label() already prefers this format)
                # rather than inventing an Amass-shaped id for a non-Amass record.
                amass_id=f"PMID:{pmid}",
                title=docs.get(pmid, {}).get("title", "").strip(),
                abstract=extra.get(pmid, {}).get("abstract"),
                doi=extra.get(pmid, {}).get("doi"),
                pmid=pmid,
            )
            for pmid in pmids
        ]

    def count_direct(self, a: str, c: str) -> int:
        """Same measurement as AmassPaperRepository, cheaper: E-utilities
        reports the match count directly, no need to fetch any records."""
        search = _ncbi_get(
            PUBMED_ESEARCH_URL,
            {"db": "pubmed", "term": f'"{a}" AND "{c}"', "retmode": "json", "retmax": 0},
        )
        return int(search.json().get("esearchresult", {}).get("count", 0))


class ClinicalTrialsRepository:
    """Keyless fallback for AmassTrialRepository: ClinicalTrials.gov API v2."""

    def __init__(self, limit: int = KEYLESS_LIMIT) -> None:
        self.limit = limit

    def find(self, query: LiteratureQuery) -> list[Paper]:
        response = _get_with_retry(
            CLINICALTRIALS_URL,
            {"query.term": query.text, "pageSize": self.limit, "format": "json"},
        )
        return [self._to_paper(study) for study in response.json().get("studies", [])]

    @staticmethod
    def _to_paper(study: dict) -> Paper:
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status = proto.get("statusModule", {})
        design = proto.get("designModule", {})
        interventions = ", ".join(
            i.get("name", "") for i in proto.get("armsInterventionsModule", {}).get("interventions", []) if i.get("name")
        )
        primary_outcomes = ", ".join(
            o.get("measure", "") for o in proto.get("outcomesModule", {}).get("primaryOutcomes", []) if o.get("measure")
        )
        nct_id = ident.get("nctId", "")
        return Paper(
            amass_id=f"NCT:{nct_id}",
            title=ident.get("briefTitle", ""),
            abstract=(
                f"{proto.get('descriptionModule', {}).get('briefSummary', '')}\n"
                f"type: {design.get('studyType')}; phase: {', '.join(design.get('phases', []) or [])}; "
                f"status: {status.get('overallStatus')}\n"
                f"interventions: {interventions}\n"
                f"primary outcomes: {primary_outcomes}"
            ),
            nct_id=nct_id,
            url=f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else None,
        )

    def count_direct(self, a: str, c: str) -> int:
        response = _get_with_retry(
            CLINICALTRIALS_URL,
            {"query.term": f'"{a}" AND "{c}"', "pageSize": 1, "countTotal": "true", "format": "json"},
        )
        return int(response.json().get("totalCount", 0))


class ClaudeRelevanceRanker(_CachingAdapter):
    """Stage 3. Scores relevance to the question, not prominence."""

    def rank(self, question: ScientificQuestion, papers: list[Paper]) -> list[RankedPaper]:
        by_id = {paper.amass_id: paper for paper in papers}
        candidates = "\n\n".join(
            f"{paper.amass_id}\n{paper.title}\n{(paper.abstract or '')[:ABSTRACT_CHARS]}"
            for paper in papers
        )
        ranking = self._call(
            "You rank publications by how directly they bear on a research question.\n\n"
            f"Question:\n{question.text}\n"
            f"Mechanism: {question.mechanism or 'unspecified'}\n"
            f"Endpoint: {question.endpoint or 'unspecified'}\n\n"
            f"Candidates:\n{candidates}\n\n"
            "Score every candidate from 0 to 1 — direct mechanistic evidence high, "
            "topical adjacency low. Use the exact IDs given. One sentence each on what "
            "the paper contributes.",
            _Ranking,
        )
        return [
            RankedPaper(
                paper=by_id[scored.amass_id], score=scored.score, rationale=scored.rationale
            )
            for scored in ranking.papers
            if scored.amass_id in by_id
        ]


# --- replay ----------------------------------------------------------------


class RecordedRun:
    """Replays a captured RunTrace. Satisfies all five ports at once.

    The fixture is a recording of a real run, not fabricated data — hand-written
    Amass records would mean inventing biology, which the project rules forbid.
    """

    def __init__(self, trace: RunTrace) -> None:
        self.trace = trace
        self._papers_served = False
        self._direct = {
            frozenset({claim.pair.a.name.lower(), claim.pair.c.name.lower()}): (
                claim.pair.direct_papers or 0
            )
            for claim in trace.claims
        }

    @classmethod
    def load(cls, path: Path = FIXTURE_PATH) -> RecordedRun:
        return cls(RunTrace.model_validate_json(path.read_text()))

    def formalize(self, raw: str) -> ScientificQuestion:
        return self.trace.question

    def search(self, question: ScientificQuestion) -> list[WebSnippet]:
        return self.trace.snippets

    def extract(
        self, question: ScientificQuestion, snippets: list[WebSnippet]
    ) -> list[BiologicalEntity]:
        return self.trace.entities

    def find(self, query: LiteratureQuery) -> list[Paper]:
        # ponytail: the whole recorded set comes back on the first call and
        # nothing after, so gather()'s dedupe still runs over real data. One
        # recorded run per fixture file; --fixtures prints the recorded question
        # so a mismatch with what you meant to ask is visible.
        if self._papers_served:
            return []
        self._papers_served = True
        return self.trace.papers

    def count_direct(self, a: str, c: str) -> int:
        return self._direct.get(frozenset({a.lower(), c.lower()}), 0)

    def rank(self, question: ScientificQuestion, papers: list[Paper]) -> list[RankedPaper]:
        return self.trace.ranked
