"""SRC radio trainer: task catalogue, grader parsing and the /api/funk route."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.providers.base import LLMResponse  # noqa: E402
from backend.funk import grader  # noqa: E402
from backend.funk.tasks import TASKS, get_task  # noqa: E402
from backend.server.app import app  # noqa: E402

client = TestClient(app)


class FakeProvider:
    model = "fake-model"

    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def complete(self, prompt: str, max_tokens: int) -> LLMResponse:
        self.prompts.append(prompt)
        return LLMResponse(text=self.text, model=self.model)


GOOD_ANSWER = """```json
{"checklist": [{"item": "Notzeichen MAYDAY dreimal", "status": "ok", "comment": ""},
               {"item": "POSITION", "status": "weird", "comment": "Länge fehlt"}],
 "score": 140, "passed": true, "summary": "Gut.", "tips": ["Langsamer sprechen", ""]}
```"""


def test_task_ids_are_unique_and_every_task_has_a_checklist():
    assert len({t.id for t in TASKS}) == len(TASKS)
    for task in TASKS:
        assert task.checklist and task.reference and task.situation


def test_public_view_withholds_the_answer():
    for task in TASKS:
        public = task.public()
        assert "reference" not in public and "checklist" not in public
        assert "call_sign_spoken" not in public["own_ship"]


def test_grade_normalizes_the_models_answer():
    task = get_task("mayday-feuer")
    provider = FakeProvider(GOOD_ANSWER)
    result = grader.grade(task, "may day may day may day this is Seeschwalbe ...", provider)
    assert result["score"] == 100
    assert result["passed"] is True
    assert result["checklist"][1]["status"] == "fehlerhaft"
    assert result["tips"] == ["Langsamer sprechen"]
    assert result["reference"] == task.reference
    assert result["model"] == "fake-model"
    assert "Seeschwalbe" in provider.prompts[0]


def test_grade_accepts_unfenced_json():
    result = grader.grade(get_task("fehlalarm"), "all stations", FakeProvider('Here: {"score": 40, "passed": false}'))
    assert result["score"] == 40 and result["passed"] is False and result["checklist"] == []


def test_grade_rejects_empty_transcript_and_unreadable_answer():
    with pytest.raises(ValueError):
        grader.grade(get_task("fehlalarm"), "   ", FakeProvider(GOOD_ANSWER))
    with pytest.raises(ValueError):
        grader.grade(get_task("fehlalarm"), "all stations", FakeProvider("no json here"))


def test_list_route_returns_public_tasks():
    body = client.get("/api/funk").json()
    assert [t["id"] for t in body["tasks"]] == [t.id for t in TASKS]


def test_grade_route_unknown_task_and_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert client.post("/api/funk", json={"task_id": "nope", "transcript": "x"}).status_code == 404
    assert client.post("/api/funk", json={"task_id": "fehlalarm", "transcript": "x"}).status_code == 400


def test_grade_route_uses_the_provider(monkeypatch):
    import backend.server.app as app_module

    monkeypatch.setattr(app_module, "get_provider", lambda keys, tier="main": FakeProvider(GOOD_ANSWER))
    response = client.post("/api/funk", json={"task_id": "mayday-feuer", "transcript": "mayday"})
    assert response.status_code == 200
    assert response.json()["passed"] is True
