"""Every route the frontend calls must stay ONE segment past /api.

This Vercel account's catch-all Python function (`api/[...path].py`) only
matches a single path segment: `/api/config` reaches the backend, but
`/api/run/<id>/evaluate` 404s at the platform level with the function never
invoked. That silently broke "Evaluate with AI" in production twice — once
before it was diagnosed, and again after a deploy that looked fine locally,
because locally `uvicorn` serves every depth happily.

Two attempts at fixing it with a `vercel.json` rewrite failed, the second
taking working routes down with it (docs/DEPLOY.md's routing section). So
the contract is the route shape itself, and this test is what holds it.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.server.app import app  # noqa: E402

client = TestClient(app)

# Called by frontend/src/lib/api.ts and lib/runStream.ts. Anything added here
# must be reachable on the deployed host, so it must be one segment deep.
FRONTEND_ROUTES = ["/api/config", "/api/models", "/api/tools", "/api/tool", "/api/run", "/api/evaluate"]


@pytest.mark.parametrize("path", FRONTEND_ROUTES)
def test_frontend_routes_are_one_segment_past_api(path):
    assert path.count("/") == 2, f"{path} is deeper than the platform's catch-all can match"


@pytest.mark.parametrize("path", FRONTEND_ROUTES)
def test_every_frontend_route_is_actually_registered(path):
    registered = {getattr(r, "path", "") for r in app.routes}
    assert path in registered, f"{path} is not served — the frontend would 404"


def test_the_frontend_only_calls_routes_on_that_list():
    """Catches a new fetch() to a deeper path at review time rather than in
    production."""
    import re

    root = Path(__file__).resolve().parent.parent / "frontend" / "src"
    called = set()
    for source in list(root.rglob("*.ts")) + list(root.rglob("*.tsx")):
        for match in re.finditer(r"API_BASE\}(/api/[A-Za-z0-9_/\-]*)", source.read_text()):
            called.add(match.group(1).rstrip("/"))
    unknown = called - set(FRONTEND_ROUTES)
    assert not unknown, f"frontend calls routes this test does not cover: {sorted(unknown)}"
    for path in called:
        assert path.count("/") == 2, f"frontend calls {path}, which is too deep for the deployed host"


def test_evaluate_takes_the_run_id_in_the_body_not_the_path():
    """A missing LLM key is a 400 from the handler — proof the request
    reached it, which is all this asserts."""
    response = client.post(
        "/api/evaluate",
        json={"comment": "", "api_keys": {}, "run_id": "abc123",
              "run_result": {"report": "## Hypothesis\n\nx", "hypotheses": [], "evidence": {}}},
    )
    assert response.status_code != 404, "the flat evaluate route must exist"
    assert response.status_code == 400


def test_the_flat_tool_toggle_works_and_rejects_a_missing_name():
    assert client.post("/api/tool", json={"name": "pubmed", "enabled": False}).json() == {
        "name": "pubmed", "enabled": False
    }
    assert client.post("/api/tool", json={"name": "pubmed", "enabled": True}).json()["enabled"] is True
    assert client.post("/api/tool", json={"enabled": True}).status_code == 400
    assert client.post("/api/tool", json={"name": "nope", "enabled": True}).status_code == 404


def test_a_rejected_key_on_evaluate_is_a_readable_400_not_a_500():
    """The run loop already turns a provider auth failure into its own
    user-actionable message. Evaluate let it through as a bare 500, so a
    stale key showed up in the UI as "evaluate failed (500)"."""
    import anthropic

    from backend.server import app as app_module

    class _Rejecting:
        name, model, key_source = "anthropic", "claude-sonnet-5", "user"

        def complete(self, prompt, max_tokens):
            raise anthropic.AuthenticationError(
                "invalid x-api-key",
                response=httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
                body=None,
            )

    import httpx

    original = app_module.get_provider
    app_module.get_provider = lambda *a, **k: _Rejecting()
    try:
        response = client.post(
            "/api/evaluate",
            json={"comment": "", "api_keys": {"ANTHROPIC_API_KEY": "bad"}, "run_id": "x",
                  "run_result": {"report": "## Hypothesis\n\nx",
                                 "hypotheses": [{"id": "h1", "statement": "s", "selected": True}], "evidence": {}}},
        )
    finally:
        app_module.get_provider = original
    assert response.status_code == 400
    assert "rejected by the provider" in response.json()["detail"]
