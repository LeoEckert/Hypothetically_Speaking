"""Admin dashboard support: auth for the /api/admin/* routes, backend API-key
rotation, and a best-effort usage/credit snapshot across providers.

Key rotation writes to two places, deliberately not just the VM's main .env:
1. `os.environ` directly, for immediate effect — every tool/client in this
   codebase reads its API key fresh from os.environ per call (no cached
   client instances), so this alone makes a rotated key work on the very
   next request.
2. A dedicated override file (`ADMIN_OVERRIDES_PATH`), loaded with
   `override=True` after the main .env at process start (see app.py). This
   exists because the backend container gets its env via docker-compose's
   `env_file: .env`, which only injects env vars at container *creation* —
   the container has no filesystem path to the host's .env to rewrite it.
   Without a mounted override file, a rotated key would revert silently on
   the next `docker compose up -d --build` (i.e. the next push to main).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from pathlib import Path
from typing import Iterator, Literal

import httpx
from fastapi import Header, HTTPException, Request

from backend.agent import costs
from backend.tools import amass_tool

ROTATABLE_KEYS = {"ANTHROPIC_API_KEY", "TAVILY_API_KEY", "AMASS_API_KEY", "NEBIUS_API_KEY"}

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

# Defaults to <repo-root>/admin_overrides.env locally and to
# /app/admin_overrides.env in the container (this file lives at
# backend/agent/admin.py, so three parents up is the repo root / WORKDIR in
# both cases) — matches the bind mount in docker-compose.yml without needing
# a separate env var for it, though ADMIN_OVERRIDES_PATH can still override.
ADMIN_OVERRIDES_PATH = Path(
    os.environ.get("ADMIN_OVERRIDES_PATH") or (Path(__file__).resolve().parent.parent.parent / "admin_overrides.env")
)

_LOCKOUT_THRESHOLD = 5
_LOCKOUT_SECONDS = 60
_failed_attempts: dict[str, tuple[int, float]] = {}  # client key -> (count, locked_until monotonic ts)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_admin_token(request: Request, x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> None:
    """FastAPI dependency guarding every /api/admin/* route. Fails closed:
    no ADMIN_TOKEN configured means the dashboard is unreachable, not open."""
    admin_token = os.environ.get("ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(status_code=503, detail="admin dashboard not configured (ADMIN_TOKEN unset)")

    key = _client_key(request)
    now = time.monotonic()
    count, locked_until = _failed_attempts.get(key, (0, 0.0))
    if now < locked_until:
        raise HTTPException(status_code=429, detail="too many failed attempts — try again shortly")

    if not x_admin_token or not compare_digest(x_admin_token, admin_token):
        count += 1
        locked_until = now + _LOCKOUT_SECONDS if count >= _LOCKOUT_THRESHOLD else 0.0
        _failed_attempts[key] = (count, locked_until)
        raise HTTPException(status_code=401, detail="invalid admin token")

    _failed_attempts.pop(key, None)


def _mask(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return "…" + value[-6:]


def _override_names() -> set[str]:
    if not ADMIN_OVERRIDES_PATH.exists():
        return set()
    names = set()
    for line in ADMIN_OVERRIDES_PATH.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            names.add(line.split("=", 1)[0].strip())
    return names


def list_keys() -> list[dict]:
    overridden = _override_names()
    out = []
    for name in sorted(ROTATABLE_KEYS):
        value = os.environ.get(name, "")
        if not value:
            out.append({"name": name, "masked": None, "source": "unset"})
        else:
            out.append({"name": name, "masked": _mask(value), "source": "override" if name in overridden else "base"})
    return out


def set_key(name: str, value: str) -> dict:
    if name not in ROTATABLE_KEYS:
        raise HTTPException(status_code=400, detail=f"'{name}' is not a rotatable key. Rotatable: {sorted(ROTATABLE_KEYS)}")
    value = (value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="value must not be empty")

    os.environ[name] = value

    ADMIN_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ADMIN_OVERRIDES_PATH.read_text().splitlines() if ADMIN_OVERRIDES_PATH.exists() else []
    prefix = f"{name}="
    new_line = f"{name}={value}"
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    # write_text() truncates-and-writes the existing inode in place — safe
    # for a bind-mounted file (unlike a write-temp-then-rename swap, which
    # would detach the mount from the file docker-compose is watching).
    ADMIN_OVERRIDES_PATH.write_text("\n".join(lines) + "\n")

    return {"name": name, "updated": True, "masked": _mask(value)}


def _amass_usage() -> dict:
    remaining = amass_tool.get_credits()
    if remaining is None:
        return {"rate_configured": False, "note": "AMASS_API_KEY/AMASS_API_URL not configured or unreachable"}
    return {"rate_configured": True, "remaining_credits": remaining}


def _anthropic_usage() -> dict:
    admin_key = os.environ.get("ANTHROPIC_ADMIN_KEY")
    if not admin_key:
        return {
            "rate_configured": False,
            "note": "ANTHROPIC_ADMIN_KEY not configured (this Admin API is also unavailable on individual/non-org Console accounts)",
        }

    ending = datetime.now(timezone.utc)
    starting = ending - timedelta(days=7)
    headers = {"anthropic-version": "2023-06-01", "x-api-key": admin_key}
    params = {
        "starting_at": starting.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ending_at": ending.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bucket_width": "1d",
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get("https://api.anthropic.com/v1/organizations/cost_report", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 — this is a monitoring panel, never let it 500 the endpoint
        return {"rate_configured": False, "note": f"Anthropic Admin API call failed: {exc}"}

    daily = []
    total_usd = 0.0
    for bucket in data.get("data", []):
        bucket_usd = sum(float(r["amount"]) for r in bucket.get("results", []) if r.get("amount") is not None) / 100
        daily.append({"starting_at": bucket.get("starting_at"), "usd": bucket_usd})
        total_usd += bucket_usd

    return {
        "rate_configured": True,
        "total_usd_last_7d": total_usd,
        "daily": daily,
        "note": "historical spend, not a remaining-credit balance — Anthropic's API doesn't expose one",
    }


def _iter_reports(reports_dir: Path = REPORTS_DIR) -> Iterator[tuple[Path, dict]]:
    """Yield (path, report_dict) for every parseable saved run report,
    silently skipping unreadable/malformed files — one bad/partial report
    must never break a whole aggregate view."""
    if not reports_dir.exists():
        return
    for path in reports_dir.glob("*.json"):
        try:
            yield path, json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            continue


def _local_report_aggregate(reports_dir: Path = REPORTS_DIR) -> dict:
    """Sum the tavily/nebius cost fields already computed per-run by
    backend/agent/costs.py across every saved report — there's no live
    balance API for either provider, so this is the best available signal."""
    totals = {
        "tavily": {"usd": 0.0, "calls": 0, "rate_configured": True},
        "nebius": {"usd": 0.0, "calls": 0, "rate_configured": True},
    }
    run_count = 0
    for _path, report in _iter_reports(reports_dir):
        cost = report.get("cost") or {}
        run_count += 1
        for provider in ("tavily", "nebius"):
            entry = cost.get(provider) or {}
            totals[provider]["calls"] += entry.get("calls", 0) or 0
            if entry.get("rate_configured"):
                totals[provider]["usd"] += entry.get("usd") or 0.0
            else:
                totals[provider]["rate_configured"] = False

    for provider, t in totals.items():
        if not t["rate_configured"]:
            t["usd"] = None
    totals["runs_counted"] = run_count
    return totals


def _report_bucket(path: Path, report: dict, granularity: Literal["day", "hour"]) -> str:
    """UTC bucket key for a report: earliest trace timestamp, falling back to
    file mtime if trace is empty. Always UTC so buckets don't shift depending
    on the machine's local timezone (dev laptop vs VM)."""
    trace = report.get("trace") or []
    timestamps = [t["timestamp"] for t in trace if "timestamp" in t]
    ts = min(timestamps) if timestamps else path.stat().st_mtime
    fmt = "%Y-%m-%dT%H:00" if granularity == "hour" else "%Y-%m-%d"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(fmt)


def _anthropic_usage_api_hourly(hours: int) -> list[dict] | None:
    """Real per-hour Anthropic $, sourced from Anthropic's own Usage API
    (token counts, priced with our confirmed rate table) rather than our
    locally-computed per-run costs. Anthropic's Cost API is daily-only and
    can't do this; the Usage API supports hourly buckets. Returns None (never
    raises) if ANTHROPIC_ADMIN_KEY is unset or the call fails — same
    graceful-degrade pattern as _anthropic_usage(), so callers fall back to
    the local aggregation."""
    admin_key = os.environ.get("ANTHROPIC_ADMIN_KEY")
    if not admin_key:
        return None

    ending = datetime.now(timezone.utc)
    starting = ending - timedelta(hours=hours)
    headers = {"anthropic-version": "2023-06-01", "x-api-key": admin_key}
    params = {
        "starting_at": starting.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ending_at": ending.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bucket_width": "1h",
        "group_by[]": "model",
        "limit": hours,
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                "https://api.anthropic.com/v1/organizations/usage_report/messages",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 — this is a monitoring panel, never let it 500 the endpoint
        return None

    out = []
    for bucket in data.get("data", []):
        bucket_key = datetime.fromisoformat(bucket["starting_at"].replace("Z", "+00:00")).strftime("%Y-%m-%dT%H:00")
        usd_sum = 0.0
        all_priced = True
        for row in bucket.get("results", []):
            cache_creation = row.get("cache_creation") or {}
            cache_write = cache_creation.get("ephemeral_5m_input_tokens", 0) + cache_creation.get(
                "ephemeral_1h_input_tokens", 0
            )
            usd, priced = costs.anthropic_cost_usd(
                row.get("model"),
                row.get("uncached_input_tokens", 0),
                row.get("output_tokens", 0),
                cache_write,
                row.get("cache_read_input_tokens", 0),
            )
            if priced:
                usd_sum += usd
            else:
                all_priced = False
        out.append({"bucket": bucket_key, "usd": usd_sum if all_priced else None, "rate_configured": all_priced})
    return out


def _empty_history_bucket() -> dict:
    return {
        "runs": 0,
        "anthropic": {"usd_sum": 0.0, "all_priced": True, "any_runs": False},
        "nebius": {"usd_sum": 0.0, "all_priced": True, "any_runs": False},
        "tavily": {"usd_sum": 0.0, "all_priced": True, "any_runs": False},
        "amass": {"credits_sum": 0.0, "any_data": False},
    }


def get_usage_history(
    granularity: Literal["day", "hour"] = "day",
    days: int = 30,
    hours: int = 24,
    reports_dir: Path = REPORTS_DIR,
) -> dict:
    """Bucketed usage/cost series, day- or hour-granular. Built from locally
    saved run reports for nebius/tavily/amass (no live API exists for any of
    them) and, at hour granularity, from Anthropic's own Usage API for
    anthropic when ANTHROPIC_ADMIN_KEY is configured — falling back to the
    same local aggregation otherwise. No live network calls at day
    granularity (kept a separate endpoint from get_usage_snapshot() so its
    latency/failure profile stays independent).

    Every dollar figure follows the same never-show-$-without-a-configured-
    rate rule as _local_report_aggregate()/costs.py: a bucket with zero runs
    is genuinely $0 (rate_configured=True), a bucket where every run was
    priced sums to a real number, and a bucket where any run was unpriced
    reports usd=None/rate_configured=False for that whole bucket rather than
    a misleading partial sum.
    """
    if granularity == "hour":
        hours = max(1, min(hours, 168))
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        keys = [(now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(hours - 1, -1, -1)]
    else:
        days = max(1, min(days, 365))
        today = datetime.now(timezone.utc).date()
        keys = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]

    buckets = {k: _empty_history_bucket() for k in keys}
    for path, report in _iter_reports(reports_dir):
        key = _report_bucket(path, report, granularity)
        bucket = buckets.get(key)
        if bucket is None:
            continue  # outside the requested window
        cost = report.get("cost") or {}
        bucket["runs"] += 1
        for provider in ("anthropic", "nebius", "tavily"):
            entry = cost.get(provider) or {}
            pb = bucket[provider]
            pb["any_runs"] = True
            if entry.get("rate_configured"):
                pb["usd_sum"] += entry.get("usd") or 0.0
            else:
                pb["all_priced"] = False
        credits_used = (cost.get("amass") or {}).get("credits_used")
        if credits_used is not None:
            bucket["amass"]["credits_sum"] += credits_used
            bucket["amass"]["any_data"] = True

    anthropic_live = _anthropic_usage_api_hourly(hours) if granularity == "hour" else None
    anthropic_live_by_key = {row["bucket"]: row for row in anthropic_live} if anthropic_live else None

    series = []
    totals = {
        "anthropic_usd": 0.0, "anthropic_priced": True,
        "nebius_usd": 0.0, "nebius_priced": True,
        "tavily_usd": 0.0, "tavily_priced": True,
        "amass_credits_used": 0.0,
        "runs": 0,
    }
    for k in keys:
        b = buckets[k]
        point: dict = {"date": k, "runs": b["runs"]}

        if anthropic_live_by_key is not None:
            live = anthropic_live_by_key.get(k, {"usd": 0.0, "rate_configured": True})
            point["anthropic"] = {"usd": live["usd"], "rate_configured": live["rate_configured"], "source": "anthropic_usage_api"}
            if live["rate_configured"]:
                totals["anthropic_usd"] += live["usd"]
            else:
                totals["anthropic_priced"] = False
            providers = ("nebius", "tavily")
        else:
            providers = ("anthropic", "nebius", "tavily")

        for provider in providers:
            pb = b[provider]
            if not pb["any_runs"]:
                point[provider] = {"usd": 0.0, "rate_configured": True, "source": "local_reports"}
            elif pb["all_priced"]:
                point[provider] = {"usd": pb["usd_sum"], "rate_configured": True, "source": "local_reports"}
                totals[f"{provider}_usd"] += pb["usd_sum"]
            else:
                point[provider] = {"usd": None, "rate_configured": False, "source": "local_reports"}
                totals[f"{provider}_priced"] = False

        credits_used = b["amass"]["credits_sum"] if b["amass"]["any_data"] else 0.0
        point["amass"] = {"credits_used": credits_used}
        totals["amass_credits_used"] += credits_used
        totals["runs"] += b["runs"]
        series.append(point)

    for provider in ("anthropic", "nebius", "tavily"):
        if not totals.pop(f"{provider}_priced"):
            totals[f"{provider}_usd"] = None

    return {
        "granularity": granularity,
        "days": days if granularity == "day" else None,
        "hours": hours if granularity == "hour" else None,
        "start_date": keys[0],
        "end_date": keys[-1],
        "series": series,
        "totals": totals,
    }


def get_usage_snapshot() -> dict:
    local = _local_report_aggregate()
    return {
        "amass": _amass_usage(),
        "anthropic": _anthropic_usage(),
        "tavily": {**local["tavily"], "source": "aggregated from saved run reports"},
        "nebius": {**local["nebius"], "source": "aggregated from saved run reports"},
        "runs_counted": local["runs_counted"],
    }
