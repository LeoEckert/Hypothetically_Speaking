"""POST /api/evaluate streams its progress.

The judge and revise passes are two long single LLM calls. As a plain
request/response the button read "Evaluating…" for their whole duration with
nothing else on screen, which is indistinguishable from a hang — that is the
report this covers. The endpoint now streams the same way POST /api/run
does: a `phase` event as each pass starts, a `progress` event about once a
second while the model writes, then `evaluation` and `stream_end`.
"""
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.providers.base import LLMResponse  # noqa: E402
from backend.server import app as app_module  # noqa: E402

RUN_RESULT = {
    "report": (
        "## Hypothesis\n\nSIRT1 activation extends healthspan [PMID:111].\n\n"
        "## Evidence That Supports It\n\nStrong data [PMID:111]\n\n"
        "## Evidence That Doesn't / Contradicts It\n\nCaveats [PMID:111]\n\n"
        "## Confidence & Uncertainty\n\nMedium.\n\n## Failure Modes\n\nOff-target.\n\n"
        "## Next Experiment To Run\n\nA cohort study.\n"
    ),
    "hypotheses": [{"id": "h1", "statement": "S", "selected": True, "evidence_ids": ["PMID:111"],
                    "contradicting_ids": [], "confidence": "medium"}],
    "evidence": {"PMID:111": {"source": "pubmed", "summary": "s", "url": "u"}},
}

JUDGE = '```json\n{"critiques": [{"section": "evidence_for", "critique": "ok", "findings": []}]}\n```'
REVISE = ('```json\n{"sections": {"evidence_for": "Revised [PMID:111]"}, "change_log": [], '
          '"unresolved": [], "confidence": "medium"}\n```')


class _StreamingProvider:
    """Emits text in several chunks so the progress ticker has something to
    report, like a real model writing a long answer."""

    name, model, key_source = "anthropic", "claude-sonnet-5", "user"

    def __init__(self):
        self.calls = 0
        self.streamed = 0

    def stream(self, system, transcript, max_tokens, on_chunk):
        self.calls += 1
        self.streamed += 1
        text = JUDGE if self.calls == 1 else REVISE
        for i in range(0, len(text), 40):
            on_chunk(text[i : i + 40])
        return LLMResponse(
            text=text,
            usage={"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            model=self.model,
        )

    def complete(self, prompt, max_tokens):
        raise AssertionError("the streaming path should be used when a listener is attached")


def _events(monkeypatch, provider=None):
    provider = provider or _StreamingProvider()
    monkeypatch.setattr(app_module, "get_provider", lambda *a, **k: provider)
    with TestClient(app_module.app) as client:
        with client.stream(
            "POST", "/api/evaluate",
            json={"comment": "", "api_keys": {"ANTHROPIC_API_KEY": "k"}, "run_id": "r1", "run_result": RUN_RESULT},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            events = [
                json.loads(line[len("data: "):])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]
    return events, provider


def test_the_stream_reports_both_passes_before_the_result(monkeypatch):
    events, provider = _events(monkeypatch)
    kinds = [e["type"] for e in events]

    assert kinds[-1] == "stream_end"
    assert "evaluation" in kinds
    assert kinds.index("evaluation") < kinds.index("stream_end")
    phases = [e["phase"] for e in events if e["type"] == "phase"]
    assert phases == ["judge", "revise"], "both passes announce themselves, in order"
    assert provider.streamed == 2, "streamed rather than waiting on two silent calls"


def test_progress_events_carry_a_growing_character_count(monkeypatch):
    events, _ = _events(monkeypatch)
    progress = [e for e in events if e["type"] == "progress"]
    assert progress, "the UI needs something to show while the model writes"
    assert {e["phase"] for e in progress} == {"judge", "revise"}
    for phase in ("judge", "revise"):
        counts = [e["chars"] for e in progress if e["phase"] == phase]
        assert counts == sorted(counts), "character counts only ever go up within a pass"
        assert counts[-1] > 0


def test_the_evaluation_event_carries_the_whole_result(monkeypatch):
    events, _ = _events(monkeypatch)
    evaluation = next(e for e in events if e["type"] == "evaluation")["evaluation"]
    assert evaluation["revised"]["sections"]["evidence_for"] == "Revised [PMID:111]"
    assert len(evaluation["critiques"]) == 5, "one per rubric section, as before"
    assert evaluation["hypothesis_id"] == "h1"


def test_a_failure_mid_pass_ends_the_stream_with_an_error(monkeypatch):
    """Never leave the client waiting on a stream that has stopped
    producing — the failure arrives, then the stream closes."""

    class _Exploding(_StreamingProvider):
        def stream(self, system, transcript, max_tokens, on_chunk):
            raise RuntimeError("upstream fell over")

    events, _ = _events(monkeypatch, _Exploding())
    kinds = [e["type"] for e in events]
    assert "evaluation" not in kinds
    assert kinds[-1] == "stream_end"
    error = next(e for e in events if e["type"] == "error")
    assert "upstream fell over" in error["error"]


def test_a_missing_key_is_still_a_plain_400_not_a_stream(monkeypatch):
    """No key at all is knowable before any call is made, so it stays a
    status code rather than an error buried in a 200 stream. (Other test
    modules set a dummy key in os.environ, which get_provider would
    otherwise accept as its local-dev fallback.)"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app_module.app) as client:
        response = client.post(
            "/api/evaluate",
            json={"comment": "", "api_keys": {}, "run_id": "r1", "run_result": RUN_RESULT},
        )
    assert response.status_code == 400
