"""Unit tests for backend/agent/evaluate.py: report-section splitting and
the revise-step safeguards (dropped-section carryover, citation fabrication
check) -- offline, no network, no Anthropic client involved beyond a fake.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.evaluate import (  # noqa: E402
    RUBRIC,
    _extract_json_fence,
    evaluate_hypothesis,
    split_report_sections,
)

REPORT = """## Hypothesis
SIRT1 activation extends healthspan via mitochondrial biogenesis [PMID:111].

## Evidence That Supports It
- Strong data [PMID:111]

## Evidence That Doesn't / Contradicts It
- Some caveats [PMID:222]

## Confidence & Uncertainty
Medium confidence [PMID:111].

## Failure Modes
- Off-target effects [PMID:333]

## Next Experiment To Run
Run a cohort study [PMID:111].
"""

HYPOTHESIS = {
    "id": "h1",
    "statement": "SIRT1 activation extends healthspan.",
    "confidence": "medium",
    "evidence_ids": ["PMID:111"],
    "contradicting_ids": ["PMID:222"],
    "seed_question": "does sirt1 activation extend healthspan?",
    "rank": 1,
    "selected": True,
    "rationale": "because reasons [PMID:111]",
}

EVIDENCE = {
    "PMID:111": {"id": "PMID:111", "source": "pubmed", "url": "http://x/111", "summary": "s1", "title": "t1"},
    "PMID:222": {"id": "PMID:222", "source": "pubmed", "url": "http://x/222", "summary": "s2", "title": "t2"},
    "PMID:333": {"id": "PMID:333", "source": "pubmed", "url": "http://x/333", "summary": "s3", "title": "t3"},
}


def test_split_report_sections_matches_every_rubric_section():
    sections = split_report_sections(REPORT)
    assert set(sections.keys()) == {rs["section"] for rs in RUBRIC}
    assert sections["evidence_for"] == "- Strong data [PMID:111]"
    assert sections["evidence_against"] == "- Some caveats [PMID:222]"
    assert sections["failure_modes"] == "- Off-target effects [PMID:333]"


def test_split_report_sections_never_raises_on_missing_heading():
    sections = split_report_sections("no headings here at all")
    assert all(v == "" for v in sections.values())


def test_extract_json_fence_requires_key_and_never_raises():
    text = 'prose\n```json\n{"critiques": [1, 2]}\n```'
    assert _extract_json_fence(text, "critiques") == {"critiques": [1, 2]}
    assert _extract_json_fence("no fence here", "critiques") is None
    assert _extract_json_fence("```json\n{not valid json\n```", "critiques") is None


class _FakeProvider:
    """A fake backend.agent.providers.LLMProvider — evaluate_hypothesis only
    ever calls provider.complete(prompt, max_tokens)."""

    name = "anthropic"
    model = "claude-sonnet-5"
    key_source = "user"

    def __init__(self, responses):
        self._responses = list(responses)

    def complete(self, prompt, max_tokens):
        from backend.agent.providers import LLMResponse

        text = self._responses.pop(0)
        return LLMResponse(
            text=text,
            usage={"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            model=self.model,
        )


_JUDGE_RESPONSE = """Reasoning...
```json
{"critiques": [
  {"section": "evidence_for", "critique": "solid", "findings": []},
  {"section": "evidence_against", "critique": "thin", "findings": []},
  {"section": "confidence_uncertainty", "critique": "ok", "findings": []},
  {"section": "failure_modes", "critique": "ok", "findings": []},
  {"section": "next_experiment", "critique": "ok", "findings": []}
]}
```"""


def _run(revise_response: str, run_result: dict | None = None) -> dict:
    provider = _FakeProvider([_JUDGE_RESPONSE, revise_response])
    result = run_result or {
        "report": REPORT,
        "hypotheses": [dict(HYPOTHESIS)],
        "evidence": dict(EVIDENCE),
    }
    return evaluate_hypothesis(result, "check the counter-evidence", provider)


def test_a_dropped_section_is_carried_over_and_recorded_not_lost():
    revise_response = """```json
{
  "statement": "Revised statement.",
  "confidence": "medium",
  "confidence_reason": "still thin",
  "sections": {
    "evidence_for": "- Strong data [PMID:111]",
    "evidence_against": "- Some caveats [PMID:222]",
    "confidence_uncertainty": "Medium confidence [PMID:111].",
    "failure_modes": "- Off-target effects [PMID:333]"
  },
  "change_log": [],
  "unresolved": []
}
```"""
    result = _run(revise_response)
    # next_experiment was omitted by the model -> carried over from the original report.
    assert result["revised"]["sections"]["next_experiment"] == "Run a cohort study [PMID:111]."
    assert any("next_experiment" not in u and "Next Experiment To Run" in u for u in result["revised"]["unresolved"])


def test_invented_citation_is_caught_not_trusted():
    revise_response = """```json
{
  "statement": "Revised statement.",
  "confidence": "medium",
  "confidence_reason": "still thin",
  "sections": {
    "evidence_for": "- Strong data [PMID:111]",
    "evidence_against": "- Some caveats [PMID:222], plus a fake one [PMID:999]",
    "confidence_uncertainty": "Medium confidence [PMID:111].",
    "failure_modes": "- Off-target effects [PMID:333]",
    "next_experiment": "Run a cohort study [PMID:111]."
  },
  "change_log": [],
  "unresolved": []
}
```"""
    result = _run(revise_response)
    assert any("FABRICATION CHECK FAILED" in u and "PMID:999" in u for u in result["revised"]["unresolved"])


def test_reused_citations_do_not_trip_the_check():
    revise_response = """```json
{
  "statement": "Revised statement.",
  "confidence": "medium",
  "confidence_reason": "still thin",
  "sections": {
    "evidence_for": "- Strong data [PMID:111]",
    "evidence_against": "- Some caveats [PMID:222]",
    "confidence_uncertainty": "Medium confidence [PMID:111].",
    "failure_modes": "- Off-target effects [PMID:333]",
    "next_experiment": "Run a cohort study [PMID:111]."
  },
  "change_log": [],
  "unresolved": []
}
```"""
    result = _run(revise_response)
    assert not any("FABRICATION CHECK FAILED" in u for u in result["revised"]["unresolved"])


def test_every_rubric_section_gets_exactly_one_critique():
    revise_response = """```json
{"statement": "x", "confidence": "low", "confidence_reason": "y",
 "sections": {"evidence_for": "a", "evidence_against": "b", "confidence_uncertainty": "c",
              "failure_modes": "d", "next_experiment": "e"},
 "change_log": [], "unresolved": []}
```"""
    result = _run(revise_response)
    assert [c["section"] for c in result["critiques"]] == [rs["section"] for rs in RUBRIC]
