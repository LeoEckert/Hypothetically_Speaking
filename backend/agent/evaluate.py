"""On-demand "Evaluate with AI" for the run's selected hypothesis.

Ported (not copied verbatim — different stack) from the judge -> revise
hypothesis-iteration loop in github.com/lmarschall/ai-scientist
(branch feat/hypothesis-iteration-loop, src/iteration/). That module judges
a hypothesis section-by-section against a fixed rubric (human feedback where
given, an LLM judge otherwise) then revises it once. We collect a single
free-text comment rather than one box per rubric section, so there is no
per-section suppression to do -- one judge call covers all five sections,
given the comment as higher-weight context rather than an on/off switch.

Deliberately decoupled from loop.py: single-turn calls, no cumulative
message history (the main run's `messages` list isn't persisted once
run_agent returns), operating entirely on a finished run's persisted
result dict (`{"report", "hypotheses", "evidence", ...}` -- the same shape
as `_results[run_id]` in server/app.py and the `done` SSE event).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from backend.agent.costs import anthropic_cost_usd

# Verbatim from the reference module's judge.py -- the core invariant that
# keeps a "revision" from just being a more confident-sounding rewrite.
ANTI_REWARD_HACKING = (
    "Penalize confidence that outruns the cited evidence. Reward hypotheses "
    "that state what would falsify them. A more persuasive-sounding revision "
    "that is not more evidence-grounded is a worse revision."
)

# Five sections, matching prompts.py's SYSTEM_PROMPT report headings
# 1:1 (`## Evidence That Supports It`, etc). Criteria ported near-verbatim
# from the reference's rubric.yaml -- domain-appropriate, framework-agnostic
# bio-hypothesis-quality checks, no reason to rewrite them.
RUBRIC = [
    {
        "section": "evidence_for",
        "title": "Evidence That Supports It",
        "report_heading": "Evidence That Supports It",
        "criteria": [
            "Every claim carries at least one citation tag; uncited claims are flagged.",
            "The cited source supports the specific claim made -- same species, endpoint, "
            "dose and population -- rather than merely being topically related.",
            "Human evidence and model-organism evidence are distinguished, never blended "
            "into one undifferentiated list.",
            "Mechanistic plausibility is not presented as outcome evidence.",
            "Correlational or observational evidence is not presented as establishing the "
            "causal chain the hypothesis claims.",
        ],
    },
    {
        "section": "evidence_against",
        "title": "Evidence That Doesn't / Contradicts It",
        "report_heading": "Evidence That Doesn't / Contradicts It",
        "criteria": [
            "The strongest available counter-evidence is present, not a token objection.",
            "Competing mechanistic explanations are named explicitly, not gestured at.",
            "Absence of evidence is distinguished from evidence of absence.",
            "The limits of the supporting studies (model, endpoint, duration, cohort) are "
            "stated rather than left for the reader to infer.",
        ],
    },
    {
        "section": "confidence_uncertainty",
        "title": "Confidence & Uncertainty",
        "report_heading": "Confidence & Uncertainty",
        "criteria": [
            "The stated confidence level is justified by the cited evidence, not by the "
            "volume or fluency of the text.",
            "Each named gap says whether it is genuinely unknowable or simply was not "
            'retrieved -- "no tool was run for this" is not the same as "unknown to science".',
            "The prose confidence does not contradict the ranked-list confidence badge "
            "without saying why.",
            "Key uncertainties are tied to specific citations rather than stated in general.",
        ],
    },
    {
        "section": "failure_modes",
        "title": "Failure Modes",
        "report_heading": "Failure Modes",
        "criteria": [
            "Failure modes are specific and checkable, not generic caveats that would apply "
            "to any hypothesis.",
            "At least one failure mode would, if true, invalidate the core claim.",
            "Where the mechanism is pharmacological, off-target and attribution risks are "
            "covered.",
            "Translation risks (species, tissue, cohort, duration) are named.",
        ],
    },
    {
        "section": "next_experiment",
        "title": "Next Experiment To Run",
        "report_heading": "Next Experiment To Run",
        "criteria": [
            "The experiment discriminates between the competing explanations named above, "
            "rather than merely gathering more supporting data.",
            "Cohort, endpoints and duration are concrete enough to cost and schedule.",
            "The result that would falsify the hypothesis is stated explicitly.",
            "It builds on evidence and infrastructure already identified rather than "
            "assuming capability nobody has.",
            "Where the question asks about causation, the experiment establishes causation "
            "-- a manipulated variable and a control -- rather than measuring whether "
            "markers merely track the outcome.",
            "It answers the original research question as asked, not an adjacent, easier "
            "question that the available evidence happens to support.",
        ],
    },
]

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_CITATION_RE = re.compile(r"\[([A-Za-z0-9_:.-]+)\]")


def split_report_sections(report_markdown: str) -> dict[str, str]:
    """Split the report's '## Heading' sections into rubric-section-id ->
    body text. Never raises -- a missing heading just comes back as an
    empty string for that section id, matching the reference adapter's own
    defensive parsing."""
    text = report_markdown or ""
    headings = list(_HEADING_RE.finditer(text))
    by_heading: dict[str, str] = {}
    for i, m in enumerate(headings):
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        by_heading[m.group(1).strip()] = text[start:end].strip()
    return {rs["section"]: by_heading.get(rs["report_heading"], "") for rs in RUBRIC}


def _extract_json_fence(text: str, required_key: str) -> dict | None:
    """Pull a trailing ```json fence out of free-text prose, requiring the
    given top-level key so we grab the right fence even if the model's
    reasoning text happens to include another one. Never raises."""
    pattern = re.compile(
        r"```json\s*(\{.*?\"" + re.escape(required_key) + r"\".*?\})\s*```", re.DOTALL
    )
    match = pattern.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _render_critiques(critiques: list[dict]) -> str:
    lines = []
    for c in critiques:
        lines.append(f"### {c['title']} ({c['section']})")
        lines.append(f"[{c['source'].upper()}] {c['critique']}")
        for f in c["findings"]:
            lines.append(
                f"- criterion: {f['criterion']}\n"
                f"  problem: {f['problem']}\n"
                f"  why it matters: {f['why_it_matters']}\n"
                f'  evidence: "{f["evidence"]}"\n'
                f"  suggestion: {f['suggestion']}"
            )
        lines.append("")
    return "\n".join(lines).strip()


def build_judge_prompt(
    hypothesis: dict, sections: dict[str, str], evidence_lines: str, comment: str
) -> str:
    sections_block = "\n\n".join(
        f"### {rs['title']}\n{sections.get(rs['section']) or '(empty)'}" for rs in RUBRIC
    )
    criteria_block = "\n\n".join(
        f"### {rs['title']}\n" + "\n".join(f"- {c}" for c in rs["criteria"]) for rs in RUBRIC
    )
    comment_block = (
        "The scientist left this note on the hypothesis -- treat it as more informed than "
        "your own independent read, and factor it into every section it bears on:\n"
        f'"{comment}"'
        if comment
        else "The scientist left no note -- judge every section independently against the "
        "criteria below."
    )
    section_ids = ", ".join(rs["section"] for rs in RUBRIC)

    return f"""\
You are critiquing one research hypothesis, section by section, against a fixed rubric.

{ANTI_REWARD_HACKING}

## Original question
{hypothesis.get("seed_question") or "(not recorded)"}

## Hypothesis
{hypothesis.get("statement", "")}
Confidence badge: {hypothesis.get("confidence") or "unrated"}

## Current sections
{sections_block}

## Evidence linked to this hypothesis
{evidence_lines}

## Scientist's note
{comment_block}

## Rubric criteria, by section
{criteria_block}

## YOUR TASK
Produce one critique per section above, in this order: {section_ids}.

Rules:
- Every finding must quote the exact text it is about, in "evidence" -- copy it verbatim
  from the section text above. No quote, no finding.
- Every finding must name which criterion it applies to, verbatim from the list above, in
  "criterion".
- A section with nothing wrong gets an empty "findings" list and a short critique saying so
  -- do not invent problems to fill space.
- Do not relitigate a section the scientist's note already settles -- say so briefly and
  move on.

Respond with ONLY a fenced ```json code block (no prose before or after it) using exactly
this schema:

```json
{{
  "critiques": [
    {{
      "section": "evidence_for",
      "critique": "one-paragraph summary of the section's quality",
      "findings": [
        {{
          "criterion": "criterion text, verbatim from the rubric above",
          "problem": "what's wrong",
          "why_it_matters": "why this matters for the hypothesis's credibility",
          "evidence": "the exact quoted text this finding is about",
          "suggestion": "a concrete fix"
        }}
      ]
    }}
  ]
}}
```

Include exactly one entry per section listed above, using its exact section id. Emit
nothing after the closing ``` of the json block.
"""


def build_revise_prompt(
    hypothesis: dict, sections: dict[str, str], critiques: list[dict], comment: str
) -> str:
    sections_block = "\n\n".join(
        f"### {rs['title']}\n{sections.get(rs['section']) or '(empty)'}" for rs in RUBRIC
    )
    critiques_block = _render_critiques(critiques)
    comment_line = f'Scientist\'s note: "{comment}"' if comment else "(no note left)"

    return f"""\
You are revising a research hypothesis in response to critique. No new evidence was
retrieved for this revision -- you may only work with what is already below.

{ANTI_REWARD_HACKING}

## Original question
{hypothesis.get("seed_question") or "(not recorded)"}

## Current hypothesis (headline)
{hypothesis.get("statement", "")}

## Current confidence badge
{hypothesis.get("confidence") or "unrated"}

## Current sections
{sections_block}

## Critiques
{critiques_block}

## {comment_line}

## YOUR TASK
Produce one revised version of this hypothesis and all five sections.

Hard rules:
1. CITATIONS. You may re-use, re-attribute, or drop the [citation-id] markers already
   present above. You may NOT invent a new one -- no new evidence was retrieved, so any
   citation not already above would be fabricated. If a critique asks for evidence that
   does not exist, say so in "unresolved" instead of inventing it.
2. LOWERING CONFIDENCE IS A VALID REVISION. If the critiques undercut the claim, the
   honest output is a weaker hypothesis, not a better-defended one.
3. "unresolved" IS PREFERRED OVER PAPERING OVER. Anything a critique demanded that the
   available evidence cannot support goes there, stated plainly.
4. EVERY CHANGE IS LOGGED in "change_log": section, what changed, and why.
5. RETURN EVERY SECTION, including ones you did not change -- for unchanged sections,
   return the original text unaltered.
6. Do not make the writing more confident, fluent, or persuasive as an end in itself. The
   only improvements that count are ones that make the hypothesis better grounded in the
   evidence already present, or more honest about where it is not.

Respond with ONLY a fenced ```json code block (no prose before or after it) using exactly
this schema:

```json
{{
  "statement": "revised one-sentence headline",
  "confidence": "high",
  "confidence_reason": "why this confidence level given the evidence",
  "sections": {{
    "evidence_for": "revised markdown for this section",
    "evidence_against": "revised markdown for this section",
    "confidence_uncertainty": "revised markdown for this section",
    "failure_modes": "revised markdown for this section",
    "next_experiment": "revised markdown for this section"
  }},
  "change_log": [
    {{"section": "evidence_for", "what_changed": "...", "why": "..."}}
  ],
  "unresolved": ["..."]
}}
```

"confidence" must be exactly one of "high", "medium", "low". Include all five section
keys. Emit nothing after the closing ``` of the json block.
"""


def _find_selected_hypothesis(hypotheses: list[dict]) -> dict | None:
    for h in hypotheses:
        if h.get("selected"):
            return h
    return hypotheses[0] if hypotheses else None


def evaluate_hypothesis(run_result: dict, comment: str, provider) -> dict:
    """Judge the run's selected hypothesis against the rubric, then revise
    it once. Raises ValueError if the run has no hypotheses to evaluate --
    callers are expected to only invoke this on a finished run."""
    hypothesis = _find_selected_hypothesis(run_result.get("hypotheses", []))
    if hypothesis is None:
        raise ValueError("run has no hypotheses to evaluate")

    report_sections = split_report_sections(run_result.get("report", ""))
    evidence = run_result.get("evidence", {})

    # What the original report already put in front of the reader, across the
    # whole document — not just the five rubric sections, since ## Hypothesis
    # carries citations too. Used to tell a citation the reviser *invented*
    # apart from one it faithfully carried over, which are very different
    # failures and used to be reported as the same one.
    originally_cited = set(hypothesis.get("evidence_ids", [])) | set(hypothesis.get("contradicting_ids", []))
    originally_cited |= set(_CITATION_RE.findall(run_result.get("report", "") or ""))

    cited_ids = set(originally_cited)
    for body in report_sections.values():
        cited_ids |= set(_CITATION_RE.findall(body))
    cited_ids &= set(evidence)  # only ids that actually resolve in this run's registry

    evidence_lines = (
        "\n".join(
            f"[{eid}] ({evidence[eid].get('source', '')}) {evidence[eid].get('summary', '')} "
            f"— {evidence[eid].get('url', '')}"
            for eid in sorted(cited_ids)
        )
        or "(no evidence linked to this hypothesis)"
    )

    comment = (comment or "").strip()
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    def _call(prompt: str, max_tokens: int) -> str:
        resp = provider.complete(prompt, max_tokens)
        usage_totals["input_tokens"] += resp.usage.get("input_tokens", 0)
        usage_totals["output_tokens"] += resp.usage.get("output_tokens", 0)
        usage_totals["cache_creation_input_tokens"] += resp.usage.get("cache_creation_input_tokens", 0)
        usage_totals["cache_read_input_tokens"] += resp.usage.get("cache_read_input_tokens", 0)
        return resp.text

    # Generous budgets: on this model family, thinking tokens count against
    # max_tokens, and a too-small cap silently burns the whole budget on
    # thinking with zero answer text (stop_reason="max_tokens", empty text
    # block) rather than erroring -- confirmed empirically against a real
    # run while building this feature. 16000 leaves comfortable headroom
    # for a 5-section critique/revision without needing streaming.
    judge_text = _call(
        build_judge_prompt(hypothesis, report_sections, evidence_lines, comment), max_tokens=16000
    )
    judge_payload = _extract_json_fence(judge_text, "critiques") or {}
    raw_critiques = judge_payload.get("critiques", [])
    critiques_by_section = {
        c.get("section"): c for c in raw_critiques if isinstance(c, dict)
    }

    critiques = []
    for rs in RUBRIC:
        c = critiques_by_section.get(rs["section"], {})
        findings = [
            {
                "criterion": str(f.get("criterion", "")),
                "problem": str(f.get("problem", "")),
                "why_it_matters": str(f.get("why_it_matters", "")),
                "evidence": str(f.get("evidence", "")),
                "suggestion": str(f.get("suggestion", "")),
            }
            for f in c.get("findings", [])
            if isinstance(f, dict)
        ]
        critiques.append(
            {
                "section": rs["section"],
                "title": rs["title"],
                "source": "llm",
                "critique": str(c.get("critique", ""))
                or "(the judge did not return a critique for this section)",
                "findings": findings,
            }
        )

    revise_text = _call(
        build_revise_prompt(hypothesis, report_sections, critiques, comment), max_tokens=16000
    )
    revise_payload = _extract_json_fence(revise_text, "sections") or {}

    revised_sections_raw = revise_payload.get("sections", {})
    if not isinstance(revised_sections_raw, dict):
        revised_sections_raw = {}

    unresolved = [str(u) for u in (revise_payload.get("unresolved") or []) if str(u).strip()]
    change_log = [
        {
            "section": str(e.get("section", "")),
            "what_changed": str(e.get("what_changed", "")),
            "why": str(e.get("why", "")),
        }
        for e in (revise_payload.get("change_log") or [])
        if isinstance(e, dict)
    ]

    ordered_sections: dict[str, str] = {}
    for rs in RUBRIC:
        sid = rs["section"]
        value = revised_sections_raw.get(sid)
        if isinstance(value, str) and value.strip():
            ordered_sections[sid] = value.strip()
        else:
            ordered_sections[sid] = report_sections.get(sid, "")
            unresolved.append(
                f"The reviser did not return the '{rs['title']}' section; the original "
                "text was carried over unchanged."
            )

    produced_ids: set[str] = set()
    for text in ordered_sections.values():
        produced_ids |= set(_CITATION_RE.findall(text))
    # Two different failures, told apart by whether the original report had
    # already made the citation. Blaming the reviser for a marker it merely
    # carried over sends a reader hunting in the wrong place -- and reads as
    # if the evaluation itself is broken.
    unsupported = produced_ids - cited_ids
    invented = sorted(unsupported - originally_cited)
    carried_over = sorted(unsupported & originally_cited)
    if invented:
        unresolved.append(
            "FABRICATION CHECK FAILED: the revision cites " + ", ".join(invented) + ", "
            "which appear nowhere in this run's evidence and were not in the original "
            "report either -- treat these claims as unsupported."
        )
    if carried_over:
        unresolved.append(
            "The revision repeats " + ", ".join(carried_over) + " from the original report, "
            "but no such entry exists in this run's evidence registry -- the original "
            "report cited a source it never retrieved, so those claims are unsupported "
            "in either version."
        )

    confidence = revise_payload.get("confidence")
    if confidence not in ("high", "medium", "low"):
        confidence = hypothesis.get("confidence") or "low"

    revised = {
        "statement": str(revise_payload.get("statement") or hypothesis.get("statement", "")),
        "confidence": confidence,
        "confidence_reason": str(revise_payload.get("confidence_reason", "")),
        "sections": ordered_sections,
        "change_log": change_log,
        "unresolved": unresolved,
    }

    # Keyed off the actual model, not just the provider name — see costs.py.
    if provider.name == "openrouter" and provider.model.endswith(":free"):
        usd, rate_configured = 0.0, True  # genuinely free tier, not an unknown rate
    else:
        usd, rate_configured = anthropic_cost_usd(
            provider.model,
            usage_totals["input_tokens"],
            usage_totals["output_tokens"],
            usage_totals["cache_creation_input_tokens"],
            usage_totals["cache_read_input_tokens"],
        )

    return {
        "hypothesis_id": hypothesis.get("id"),
        "comment": comment,
        "model": provider.model,
        "provider": provider.name,
        "critiques": critiques,
        "revised": revised,
        "cost": {
            "usd": usd,
            "rate_configured": rate_configured,
            "free_tier": provider.name == "openrouter" and provider.model.endswith(":free"),
            "key_source": provider.key_source,
            "input_tokens": usage_totals["input_tokens"],
            "output_tokens": usage_totals["output_tokens"],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
