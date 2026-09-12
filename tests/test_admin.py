"""Tests for backend/agent/admin.py: usage-history bucketing and the
/api/admin/* route auth gate. There was no coverage of this module before.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Imported at module scope (not inside a fixture) so its load_dotenv() side
# effect happens at collection time, same as test_tools.py's os.environ.pop()
# calls — otherwise importing this lazily from within a test would reload
# real provider keys from .env after test_tools.py already cleared them,
# leaking into tests that run later in file order.
from backend.agent import admin  # noqa: E402
from backend.server.app import app as _app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _write_report(reports_dir: Path, run_id: str, timestamp: float, cost: dict) -> None:
    report = {
        "run_id": run_id,
        "trace": [{"timestamp": timestamp}],
        "cost": cost,
    }
    (reports_dir / f"{run_id}.json").write_text(json.dumps(report))


def _priced(usd: float) -> dict:
    return {"usd": usd, "rate_configured": True}


def _unpriced() -> dict:
    return {"usd": None, "rate_configured": False}


def test_history_zero_runs_day_is_zero_not_null(tmp_path):
    result = admin.get_usage_history(days=3, reports_dir=tmp_path)
    assert len(result["series"]) == 3
    for point in result["series"]:
        assert point["runs"] == 0
        for provider in ("anthropic", "nebius", "tavily"):
            assert point[provider] == {"usd": 0.0, "rate_configured": True}
        assert point["amass"] == {"credits_used": 0.0}


def test_history_all_priced_day_sums(tmp_path):
    import time

    now = time.time()
    _write_report(
        tmp_path, "r1", now,
        {"anthropic": _priced(1.0), "nebius": _priced(0.5), "tavily": _priced(0.1), "amass": {"credits_used": 2.0}},
    )
    _write_report(
        tmp_path, "r2", now,
        {"anthropic": _priced(2.0), "nebius": _priced(0.5), "tavily": _priced(0.1), "amass": {"credits_used": 3.0}},
    )
    result = admin.get_usage_history(days=1, reports_dir=tmp_path)
    point = result["series"][0]
    assert point["runs"] == 2
    assert point["anthropic"] == {"usd": 3.0, "rate_configured": True}
    assert point["nebius"] == {"usd": 1.0, "rate_configured": True}
    assert point["amass"] == {"credits_used": 5.0}
    assert result["totals"]["anthropic_usd"] == 3.0
    assert result["totals"]["runs"] == 2


def test_history_any_unpriced_run_makes_whole_day_null(tmp_path):
    import time

    now = time.time()
    _write_report(tmp_path, "r1", now, {"anthropic": _priced(1.0), "nebius": _unpriced(), "tavily": _unpriced(), "amass": {}})
    _write_report(tmp_path, "r2", now, {"anthropic": _priced(1.0), "nebius": _priced(0.5), "tavily": _unpriced(), "amass": {}})
    result = admin.get_usage_history(days=1, reports_dir=tmp_path)
    point = result["series"][0]
    assert point["anthropic"] == {"usd": 2.0, "rate_configured": True}
    assert point["nebius"] == {"usd": None, "rate_configured": False}
    assert point["tavily"] == {"usd": None, "rate_configured": False}
    assert result["totals"]["nebius_usd"] is None
    assert result["totals"]["tavily_usd"] is None
    assert result["totals"]["anthropic_usd"] == 2.0


def test_history_empty_trace_falls_back_to_mtime(tmp_path):
    report = {"run_id": "r1", "trace": [], "cost": {}}
    (tmp_path / "r1.json").write_text(json.dumps(report))
    result = admin.get_usage_history(days=1, reports_dir=tmp_path)
    assert result["series"][0]["runs"] == 1


def test_history_malformed_report_is_skipped(tmp_path):
    (tmp_path / "bad.json").write_text("{not valid json")
    result = admin.get_usage_history(days=1, reports_dir=tmp_path)
    assert result["series"][0]["runs"] == 0


def test_history_days_are_clamped(tmp_path):
    assert admin.get_usage_history(days=9999, reports_dir=tmp_path)["days"] == 365
    assert admin.get_usage_history(days=0, reports_dir=tmp_path)["days"] == 1
    assert admin.get_usage_history(days=-5, reports_dir=tmp_path)["days"] == 1


def test_history_reports_outside_window_are_excluded(tmp_path):
    import time

    old_ts = time.time() - 40 * 86400
    _write_report(tmp_path, "old", old_ts, {"anthropic": _priced(5.0), "nebius": {}, "tavily": {}, "amass": {}})
    result = admin.get_usage_history(days=7, reports_dir=tmp_path)
    assert result["totals"]["runs"] == 0


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    monkeypatch.setattr(admin, "_failed_attempts", {})
    return TestClient(_app)


def test_route_rejects_missing_token(client):
    resp = client.get("/api/admin/usage/history")
    assert resp.status_code == 401


def test_route_rejects_wrong_token(client):
    resp = client.get("/api/admin/usage/history", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_route_accepts_correct_token(client):
    resp = client.get("/api/admin/usage/history?days=7", headers={"X-Admin-Token": "test-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 7
    assert len(body["series"]) == 7


def test_route_503_when_admin_token_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(admin, "_failed_attempts", {})
    resp = TestClient(_app).get("/api/admin/usage/history", headers={"X-Admin-Token": "anything"})
    assert resp.status_code == 503
