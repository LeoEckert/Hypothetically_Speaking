"""Unit tests for the hypothesis fence-parsing/normalization helpers in
backend/agent/loop.py — these back the PLAN -> REVISE -> REPORT stable-id
lifecycle that the frontend's progress/results views depend on.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from backend.agent.loop import (  # noqa: E402
    _extract_hypotheses,
    _grounding_payload,
    _grounding_text,
    _normalize_hypotheses,
    _parse_hypotheses,
    _plan_message,
)
from backend.agent.prompts import plan_prompt  # noqa: E402


def _fence(payload: str) -> str:
    return f"some prose\n```json\n{payload}\n```"


def test_parse_hypotheses_no_fence_returns_empty():
    assert _parse_hypotheses("just prose, no fence here") == []


def test_parse_hypotheses_malformed_json_returns_empty():
    assert _parse_hypotheses(_fence('{"hypotheses": [invalid json')) == []


def test_parse_hypotheses_valid_fence():
    hyps = _parse_hypotheses(_fence('{"hypotheses": [{"statement": "x"}]}'))
    assert hyps == [{"statement": "x"}]


def test_extract_hypotheses_strips_fence_even_on_parse_failure():
    # Matches the fence regex (a balanced {...} block) but is invalid JSON
    # (trailing comma) — must still be stripped from the visible text.
    text = "## Report\n\nSome text.\n\n" + '```json\n{"hypotheses": [,]}\n```'
    stripped, hyps = _extract_hypotheses(text)
    assert "```" not in stripped
    assert hyps == []


def test_extract_hypotheses_strips_fence_on_success():
    text = "## Report\n\nSome text." + '\n```json\n{"hypotheses": [{"statement": "x"}]}\n```'
    stripped, hyps = _extract_hypotheses(text)
    assert stripped == "## Report\n\nSome text."
    assert hyps == [{"statement": "x"}]


def test_normalize_plan_assigns_stable_ids():
    raw = [{"statement": "A", "seed_question": "qa"}, {"statement": "B", "seed_question": "qb"}]
    normalized = _normalize_hypotheses(raw, "plan", {}, set())
    assert [h["id"] for h in normalized] == ["h1", "h2"]
    assert all(h["confidence"] is None for h in normalized)
    # Nothing has been evaluated yet at PLAN — never force a selection.
    assert not any(h["selected"] for h in normalized)


def test_normalize_plan_skips_entries_without_statement():
    raw = [{"statement": ""}, {"statement": "B"}]
    normalized = _normalize_hypotheses(raw, "plan", {}, set())
    assert len(normalized) == 1
    assert normalized[0]["id"] == "h1"
    assert normalized[0]["statement"] == "B"


def test_normalize_revise_drops_unrecognized_ids():
    known = {"h1": {"statement": "A", "seed_question": "qa"}}
    raw = [
        {"id": "h1", "confidence": "high", "selected": True},
        {"id": "h9", "confidence": "low", "selected": False},  # unrecognized — must be dropped
    ]
    normalized = _normalize_hypotheses(raw, "revise", known, set())
    assert len(normalized) == 1
    assert normalized[0]["id"] == "h1"


def test_normalize_enforces_exactly_one_selected():
    known = {"h1": {"statement": "A"}, "h2": {"statement": "B"}}
    raw = [
        {"id": "h1", "confidence": "high", "selected": True},
        {"id": "h2", "confidence": "medium", "selected": True},
    ]
    normalized = _normalize_hypotheses(raw, "revise", known, set())
    assert sum(1 for h in normalized if h["selected"]) == 1


def test_normalize_defaults_a_selection_when_model_gives_none():
    known = {"h1": {"statement": "A"}, "h2": {"statement": "B"}}
    raw = [
        {"id": "h1", "confidence": "high", "selected": False},
        {"id": "h2", "confidence": "medium", "selected": False},
    ]
    normalized = _normalize_hypotheses(raw, "revise", known, set())
    assert sum(1 for h in normalized if h["selected"]) == 1


def test_normalize_filters_unknown_evidence_ids():
    known = {"h1": {"statement": "A"}}
    raw = [{"id": "h1", "evidence_ids": ["PMID:1", "PMID:999"], "contradicting_ids": ["PMID:999"]}]
    normalized = _normalize_hypotheses(raw, "revise", known, {"PMID:1"})
    assert normalized[0]["evidence_ids"] == ["PMID:1"]
    assert normalized[0]["contradicting_ids"] == []


def test_normalize_malformed_fence_returns_empty_without_raising():
    assert _normalize_hypotheses("not a list", "revise", {"h1": {}}, set()) == []
    assert _normalize_hypotheses(None, "final", {"h1": {}}, set()) == []


def test_plan_message_puts_grounding_before_schema():
    text = _plan_message('{"novel_claims": []}')
    assert text.index('{"novel_claims": []}') < text.index(plan_prompt())
    assert "```json" in text


def test_grounding_text_skips_without_keys(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "AMASS_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    payload = _grounding_payload("does SIRT1 matter?")
    assert payload["status"] == "skipped"
    assert payload["triples"] == []
    assert _grounding_text(payload).startswith("(grounding skipped:")


def test_grounding_payload_preserves_the_l0_trace(monkeypatch):
    class Dumpable:
        def __init__(self, payload):
            self.payload = payload

        def model_dump(self, mode):
            assert mode == "json"
            return self.payload

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AMASS_API_KEY", "test-key")
    monkeypatch.setattr(
        "scripts.run_grounding.ground",
        lambda _question, **_options: SimpleNamespace(
            coherent=True,
            why="coherent",
            destination="B",
            rejected=[],
            triples=[Dumpable({"subject": "A", "verb": "causes", "object": "B"})],
            premises=[
                Dumpable(
                    {
                        "subject": "A",
                        "verb": "causes",
                        "object": "B",
                        "status": "UNVERIFIED",
                    }
                )
            ],
            knowledge_graph="A -causes-> B",
            hypotheses=[],
        ),
    )

    payload = _grounding_payload("Does A cause B?")
    assert payload["status"] == "complete"
    assert payload["triples"] == [{"subject": "A", "verb": "causes", "object": "B"}]
    assert payload["destination"] == "B" and payload["rejected"] == []
    assert "UNVERIFIED" in _grounding_text(payload)


def test_normalize_recovers_when_known_roster_is_empty():
    # If PLAN produced nothing, a later stage should still be able to mint
    # fresh ids rather than silently dropping every hypothesis forever.
    raw = [{"statement": "A", "confidence": "high", "selected": True}]
    normalized = _normalize_hypotheses(raw, "revise", {}, set())
    assert len(normalized) == 1
    assert normalized[0]["id"] == "h1"
    assert normalized[0]["confidence"] == "high"


def test_normalize_revise_matches_ids_case_insensitively():
    # The model echoed the grounding labels (H1) instead of PLAN's ids (h1).
    known = {"h1": {"statement": "A", "seed_question": "qa"}, "h2": {"statement": "B", "seed_question": "qb"}}
    raw = [
        {"id": "H1", "confidence": "high", "selected": True},
        {"id": " H2 ", "confidence": "low", "selected": False},
    ]
    normalized = _normalize_hypotheses(raw, "revise", known, set())
    assert [(h["id"], h["confidence"], h["selected"]) for h in normalized] == [("h1", "high", True), ("h2", "low", False)]
