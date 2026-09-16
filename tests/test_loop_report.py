"""The REPORT phase must always hand the frontend something readable.

Two ways a run used to end with a blank report area and no error at all:
the model answered with only the trailing ```json hypotheses fence (so
stripping the fence left nothing), or it returned no text whatsoever (a
free model streaming reasoning-only, or truncating before any content).
Both produced `done.report == ""`, which `ReportView` renders as an empty
card. A third way lost the report entirely: an exception in the cost
accounting that runs *after* the try block, which meant no `done` at all.

These drive run_agent end-to-end against a fake provider — no network.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from backend.agent import loop  # noqa: E402
from backend.agent.providers.base import LLMResponse  # noqa: E402

FENCE = '```json\n{"hypotheses": [{"id": "h1", "rank": 1, "statement": "S", "confidence": "high", "selected": true}]}\n```'


def _response(text: str = "") -> LLMResponse:
    return LLMResponse(
        text=text,
        stop_reason="end_turn",
        usage={"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        model="claude-sonnet-5",
    )


class _ScriptedProvider:
    """Answers every streamed phase (PLAN, REVISE, REPORT, and any re-ask)
    from a script; the last entry repeats once the script runs out."""

    name = "anthropic"
    model = "claude-sonnet-5"
    key_source = "platform"

    def __init__(self, stream_texts):
        self._texts = list(stream_texts)
        self.stream_calls: list[int] = []

    def create(self, system, transcript, tools, max_tokens):
        return _response("")

    def stream(self, system, transcript, max_tokens, on_chunk):
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        self.stream_calls.append(max_tokens)
        if text:
            on_chunk(text)
        return _response(text)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(
        loop,
        "_grounding_payload",
        lambda *args, **kwargs: {
            "status": "skipped", "why": "off for this test", "coherent": None,
            "triples": [], "destination": "", "premises": [], "knowledge_graph": "", "hypotheses": [], "rejected": [],
        },
    )
    monkeypatch.setenv("ENABLED_TOOLS", "pubmed")


def _run(monkeypatch, stream_texts):
    """Returns (done_event, provider). PLAN and REVISE take the first two
    script entries; REPORT takes the third."""
    provider = _ScriptedProvider(stream_texts)
    monkeypatch.setattr(loop, "get_provider", lambda *args, **kwargs: provider)
    events: list[dict] = []
    loop.run_agent("Does SIRT1 activation extend healthspan?", on_event=events.append, max_tool_calls=1)
    done = [e for e in events if e.get("type") == "done"]
    assert len(done) == 1, "exactly one done event must always be emitted"
    return done[0], provider


def test_a_report_that_is_only_a_hypotheses_fence_does_not_ship_empty(monkeypatch):
    """The model skipped the prose and emitted just the JSON block."""
    done, _ = _run(monkeypatch, ["plan", "revise", FENCE])
    assert done["report"].strip(), "the report must never be blank"
    assert "```" not in done["report"], "the fence must not leak into what the user reads"


def test_a_fence_emitted_before_the_prose_keeps_the_prose(monkeypatch):
    """Ordering the prompt asks for, reversed — the body must survive."""
    done, _ = _run(monkeypatch, ["plan", "revise", FENCE + "\n\n## Hypothesis\n\nSIRT1 activation is plausible."])
    assert "## Hypothesis" in done["report"]
    assert "SIRT1 activation is plausible." in done["report"]
    assert "```" not in done["report"]


def test_an_empty_report_response_is_re_asked_exactly_once(monkeypatch):
    """First REPORT call comes back blank; the retry produces real prose."""
    provider = _ScriptedProvider(["plan", "revise", "", "## Hypothesis\n\nRecovered on the second ask."])
    monkeypatch.setattr(loop, "get_provider", lambda *args, **kwargs: provider)
    events: list[dict] = []
    loop.run_agent("q", on_event=events.append, max_tool_calls=1)
    done = next(e for e in events if e.get("type") == "done")

    assert "Recovered on the second ask." in done["report"]
    assert len(provider.stream_calls) == 4, "PLAN + REVISE + REPORT + one re-ask, and no more"


def test_a_persistently_empty_report_becomes_a_readable_notice(monkeypatch):
    """Both the REPORT call and its re-ask came back empty."""
    done, provider = _run(monkeypatch, ["plan", "revise", ""])
    assert done["report"].startswith("## Report Unavailable")
    assert "claude-sonnet-5" in done["report"], "name the model that produced nothing"
    assert len(provider.stream_calls) == 4, "one re-ask, then give up"
    assert done["hypotheses"] is not None


def test_no_phase_can_ship_a_blank_report(monkeypatch):
    """Whatever the model does, `done.report` always has content — this is
    the invariant ReportView's empty card was the symptom of."""
    for script in (["plan", "revise", ""], ["plan", "revise", FENCE], ["plan", "revise", "   \n\n  "]):
        done, _ = _run(monkeypatch, script)
        assert done["report"].strip(), f"blank report for script {script!r}"


def test_cost_accounting_failure_still_emits_the_report(monkeypatch):
    """build_cost_summary runs after the try block; a raise there used to
    drop the whole done event and with it the finished report."""
    def _boom(*args, **kwargs):
        raise RuntimeError("pricing table exploded")

    monkeypatch.setattr(loop, "build_cost_summary", _boom)
    done, _ = _run(monkeypatch, ["plan", "revise", "## Hypothesis\n\nA real report."])
    assert "A real report." in done["report"]
    assert done["cost"] is None or done["cost"] == {}, "cost degrades, the report does not"


def test_amass_credit_lookup_failure_still_emits_the_report(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("amass down")

    monkeypatch.setattr(loop.amass_tool, "get_credits", _boom)
    done, _ = _run(monkeypatch, ["plan", "revise", "## Hypothesis\n\nStill here."])
    assert "Still here." in done["report"]
