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
    assert dev["main"] == dev["fast"] == "claude-haiku-4-5" and dev["allow_override"] is False
    assert prod["main"] == "claude-sonnet-5" and prod["fast"] == "claude-haiku-4-5" and prod["allow_override"]


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
    assert model_policy.anthropic_model("main", {"ANTHROPIC_MODEL": "claude-opus-5"}) == "claude-haiku-4-5"


def test_get_provider_uses_the_deployment_policy_for_anthropic(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    main = get_provider({"ANTHROPIC_API_KEY": "k"}, tier="main")
    fast = get_provider({"ANTHROPIC_API_KEY": "k"}, tier="fast")
    assert main.model == fast.model == "claude-haiku-4-5"
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


def test_no_model_id_in_the_repo_carries_a_date_suffix():
    """Anthropic's current model ids are complete as they stand; appending a
    release date produces an id the API rejects with a 404. The dev preview
    pins both tiers to Haiku, so a wrong id there kills every run on that
    deployment — cheap to assert, expensive to discover in production."""
    import re

    root = Path(__file__).resolve().parent.parent
    dated = re.compile(r"claude-[a-z0-9.-]*?-(?:20\d{6})")
    offenders = []
    for path in list(root.glob("backend/**/*.py")) + list(root.glob("backend/**/*.toml")) + list(
        root.glob("frontend/src/**/*.ts")
    ) + list(root.glob("frontend/src/**/*.tsx")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if dated.search(line):
                offenders.append(f"{path.relative_to(root)}:{number}")
    assert not offenders, f"date-suffixed Claude model ids: {offenders}"
