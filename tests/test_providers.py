"""Unit tests for backend/agent/providers: which provider get_provider()
resolves to given platform env vars vs. per-request BYOK overrides, and the
Groq provider's request/response normalization.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.providers import NoProviderAvailable, get_provider  # noqa: E402
from backend.agent.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from backend.agent.providers.groq_provider import GroqProvider  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def test_no_keys_at_all_raises_no_provider_available():
    with pytest.raises(NoProviderAvailable):
        get_provider({})


def test_platform_groq_key_is_the_default_when_no_anthropic_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "platform-groq")
    provider = get_provider({})
    assert isinstance(provider, GroqProvider)
    assert provider.key_source == "platform"


def test_user_anthropic_key_overrides_the_groq_default(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "platform-groq")
    provider = get_provider({"ANTHROPIC_API_KEY": "user-anthropic-key"})
    assert isinstance(provider, AnthropicProvider)
    assert provider.key_source == "user"


def test_platform_anthropic_key_is_used_when_no_user_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "platform-anthropic")
    provider = get_provider({})
    assert isinstance(provider, AnthropicProvider)
    assert provider.key_source == "platform"


def test_fast_tier_selects_a_different_model_than_main(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "platform-anthropic")
    main = get_provider({}, tier="main")
    fast = get_provider({}, tier="fast")
    assert main.model != fast.model


def test_groq_provider_normalizes_tool_calls_from_json_arguments():
    provider = GroqProvider(api_key="k", model="test-model")

    class _FakeFunction:
        name = "pubmed"
        arguments = '{"query": "sirt1"}'

    class _FakeToolCall:
        id = "call_1"
        function = _FakeFunction()

        def model_dump(self):
            return {"id": self.id, "function": {"name": self.function.name, "arguments": self.function.arguments}}

    message = SimpleNamespace(content=None, tool_calls=[_FakeToolCall()])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None, model="test-model")

    normalized = provider._normalize(response)
    assert normalized.stop_reason == "tool_use"
    assert normalized.tool_calls[0].name == "pubmed"
    assert normalized.tool_calls[0].input == {"query": "sirt1"}


def test_groq_provider_handles_malformed_tool_arguments_without_raising():
    provider = GroqProvider(api_key="k", model="test-model")

    class _FakeFunction:
        name = "pubmed"
        arguments = "not valid json"

    class _FakeToolCall:
        id = "call_1"
        function = _FakeFunction()

        def model_dump(self):
            return {}

    message = SimpleNamespace(content=None, tool_calls=[_FakeToolCall()])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None, model="test-model")

    normalized = provider._normalize(response)
    assert normalized.tool_calls[0].input == {}
