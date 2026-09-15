"""backend/config/models.toml + backend/agent/model_policy.py: which Claude
model each deployment gets, and when a user's own pick may replace it."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent import model_policy  # noqa: E402
from backend.agent.providers import get_provider  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("APP_ENV", "VERCEL_ENV", "ANTHROPIC_MODEL", "GROUNDING_FAST_MODEL", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    model_policy._load.cache_clear()


def test_the_shipped_policy_pins_dev_to_haiku_and_mixes_in_production():
    dev = model_policy.anthropic_policy("preview")
    prod = model_policy.anthropic_policy("production")
    assert dev["main"] == dev["fast"] == "claude-haiku-4-5-20251001" and dev["allow_override"] is False
    assert prod["main"] == "claude-sonnet-5" and prod["fast"] == "claude-haiku-4-5-20251001" and prod["allow_override"]


def test_vercel_env_selects_the_section_and_app_env_wins(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert model_policy.deployment_env() == "preview"
    monkeypatch.setenv("APP_ENV", "production")
    assert model_policy.deployment_env() == "production"
    monkeypatch.setenv("APP_ENV", "staging-typo")
    assert model_policy.deployment_env() == "development", "unknown values are not guessed at"


def test_user_override_is_honoured_in_production_but_not_on_preview(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    assert model_policy.anthropic_model("main", {"ANTHROPIC_MODEL": "claude-opus-5"}) == "claude-opus-5"
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert model_policy.anthropic_model("main", {"ANTHROPIC_MODEL": "claude-opus-5"}) == "claude-haiku-4-5-20251001"


def test_get_provider_uses_the_deployment_policy_for_anthropic(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    main = get_provider({"ANTHROPIC_API_KEY": "k"}, tier="main")
    fast = get_provider({"ANTHROPIC_API_KEY": "k"}, tier="fast")
    assert main.model == fast.model == "claude-haiku-4-5-20251001"
    monkeypatch.setenv("VERCEL_ENV", "production")
    assert get_provider({"ANTHROPIC_API_KEY": "k"}, tier="main").model == "claude-sonnet-5"


def test_missing_policy_file_falls_back_to_env_then_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(model_policy, "CONFIG_PATH", tmp_path / "nope.toml")
    model_policy._load.cache_clear()
    assert model_policy.anthropic_model("main") == "claude-sonnet-5"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5")
    assert model_policy.anthropic_model("main") == "claude-opus-5"
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    assert model_policy.anthropic_model("main") == "claude-sonnet-5", "blank env var reads as unset"
