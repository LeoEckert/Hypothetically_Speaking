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


def _local(usd, configured=True):
    return {"usd": usd, "rate_configured": configured, "source": "local_reports"}


def test_history_zero_runs_day_is_zero_not_null(tmp_path):
    result = admin.get_usage_history(days=3, reports_dir=tmp_path)
    assert len(result["series"]) == 3
    for point in result["series"]:
        assert point["runs"] == 0
        for provider in ("anthropic", "nebius", "tavily"):
            assert point[provider] == _local(0.0)
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
    assert point["anthropic"] == _local(3.0)
    assert point["nebius"] == _local(1.0)
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
    assert point["anthropic"] == _local(2.0)
    assert point["nebius"] == _local(None, configured=False)
    assert point["tavily"] == _local(None, configured=False)
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


def test_history_hour_granularity_buckets_and_falls_back_locally(tmp_path, monkeypatch):
    import time

    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
    now = time.time()
    _write_report(tmp_path, "r1", now, {"anthropic": _priced(1.5), "nebius": {}, "tavily": {}, "amass": {}})
    result = admin.get_usage_history(granularity="hour", hours=24, reports_dir=tmp_path)
    assert result["granularity"] == "hour"
    assert result["days"] is None
    assert result["hours"] == 24
    assert len(result["series"]) == 24
    current_hour_point = result["series"][-1]
    assert current_hour_point["runs"] == 1
    assert current_hour_point["anthropic"] == _local(1.5)


def test_history_hour_granularity_clamped(tmp_path):
    assert admin.get_usage_history(granularity="hour", hours=9999, reports_dir=tmp_path)["hours"] == 168
    assert admin.get_usage_history(granularity="hour", hours=0, reports_dir=tmp_path)["hours"] == 1


def test_anthropic_usage_api_hourly_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
    assert admin._anthropic_usage_api_hourly(24) is None


def test_anthropic_usage_api_hourly_returns_none_on_request_failure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_ADMIN_KEY", "fake-key")

    class _BoomClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(admin.httpx, "Client", lambda **k: _BoomClient())
    assert admin._anthropic_usage_api_hourly(24) is None


def test_anthropic_usage_api_hourly_prices_from_real_token_counts(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_ADMIN_KEY", "fake-key")

    payload = {
        "data": [
            {
                "starting_at": "2026-09-12T14:00:00Z",
                "ending_at": "2026-09-12T15:00:00Z",
                "results": [
                    {
                        "model": "claude-sonnet-5",
                        "uncached_input_tokens": 1_000_000,
                        "output_tokens": 1_000_000,
                        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0},
                        "cache_read_input_tokens": 0,
                    }
                ],
            },
            {
                "starting_at": "2026-09-12T15:00:00Z",
                "ending_at": "2026-09-12T16:00:00Z",
                "results": [
                    {
                        "model": "some-future-unpriced-model",
                        "uncached_input_tokens": 100,
                        "output_tokens": 100,
                        "cache_creation": {},
                        "cache_read_input_tokens": 0,
                    }
                ],
            },
        ],
        "has_more": False,
        "next_page": None,
    }

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _FakeResponse()

    monkeypatch.setattr(admin.httpx, "Client", lambda **k: _FakeClient())

    result = admin._anthropic_usage_api_hourly(24)
    assert result is not None
    priced_bucket = next(r for r in result if r["bucket"] == "2026-09-12T14:00")
    assert priced_bucket["rate_configured"] is True
    assert priced_bucket["usd"] == 12.0  # 1M input * $2/1M + 1M output * $10/1M

    unpriced_bucket = next(r for r in result if r["bucket"] == "2026-09-12T15:00")
    assert unpriced_bucket["rate_configured"] is False
    assert unpriced_bucket["usd"] is None


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


def test_route_hour_granularity(client):
    resp = client.get("/api/admin/usage/history?granularity=hour&hours=24", headers={"X-Admin-Token": "test-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "hour"
    assert len(body["series"]) == 24


def test_route_rejects_bad_granularity(client):
    resp = client.get("/api/admin/usage/history?granularity=bogus", headers={"X-Admin-Token": "test-token"})
    assert resp.status_code == 400


def test_route_503_when_admin_token_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(admin, "_failed_attempts", {})
    resp = TestClient(_app).get("/api/admin/usage/history", headers={"X-Admin-Token": "anything"})
    assert resp.status_code == 503
