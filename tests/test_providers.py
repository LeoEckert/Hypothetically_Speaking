"""Unit tests for backend/agent/providers: which provider get_provider()
resolves to given BYOK overrides vs. a local-dev env var, and
OpenRouterProvider's request/response normalization.

There's no platform-held LLM key in production (every user brings their own
via the frontend's required onboarding popup) — the env-var path tested here
exists only as a local-dev convenience (see providers/__init__.py's module
docstring), which is why it's still worth covering.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.providers import FallbackProvider, NoProviderAvailable, get_provider  # noqa: E402
from backend.agent.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from backend.agent.providers.openrouter_provider import OpenRouterProvider  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def test_no_keys_at_all_raises_no_provider_available():
    with pytest.raises(NoProviderAvailable):
        get_provider({})


def test_local_dev_openrouter_env_var_is_used_when_no_anthropic_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "local-dev-openrouter")
    provider = get_provider({})
    assert isinstance(provider, OpenRouterProvider)
    assert provider.key_source == "platform"


def test_both_keys_start_on_openrouter_with_claude_as_the_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "local-dev-openrouter")
    provider = get_provider({"ANTHROPIC_API_KEY": "user-anthropic-key"})
    assert isinstance(provider, FallbackProvider)
    assert isinstance(provider.primary, OpenRouterProvider) and isinstance(provider.fallback, AnthropicProvider)
    assert provider.name == "openrouter" and not provider.switched
    assert provider.primary.key_source == "platform" and provider.fallback.key_source == "user"


def test_user_openrouter_key_is_used_when_no_anthropic_key(monkeypatch):
    provider = get_provider({"OPENROUTER_API_KEY": "user-openrouter-key"})
    assert isinstance(provider, OpenRouterProvider)
    assert provider.key_source == "user"


def test_local_dev_anthropic_env_var_is_used_when_no_user_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-dev-anthropic")
    provider = get_provider({})
    assert isinstance(provider, AnthropicProvider)
    assert provider.key_source == "platform"


def test_fast_tier_selects_a_different_model_than_main(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-dev-anthropic")
    main = get_provider({}, tier="main")
    fast = get_provider({}, tier="fast")
    assert main.model != fast.model


def test_openrouter_provider_normalizes_tool_calls_from_json_arguments():
    provider = OpenRouterProvider(api_key="k", model="test-model")

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


def test_openrouter_provider_handles_malformed_tool_arguments_without_raising():
    provider = OpenRouterProvider(api_key="k", model="test-model")

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


# --- a blank-but-set env var must read as unset (Vercel declares vars with no value) ---


def test_blank_anthropic_model_env_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    monkeypatch.setenv("GROUNDING_FAST_MODEL", "   ")
    main = get_provider({"ANTHROPIC_API_KEY": "user-anthropic-key"}, tier="main")
    fast = get_provider({"ANTHROPIC_API_KEY": "user-anthropic-key"}, tier="fast")
    assert main.model == "claude-sonnet-5"
    assert fast.model == "claude-haiku-4-5-20251001"


def test_anthropic_provider_refuses_an_empty_model_name():
    import pytest

    from backend.agent.providers.anthropic_provider import AnthropicProvider

    with pytest.raises(ValueError, match="ANTHROPIC_MODEL"):
        AnthropicProvider(api_key="x", model="")


def test_env_helpers_treat_blank_as_unset(monkeypatch):
    from backend.agent.env import env_int, env_str

    monkeypatch.delenv("HS_TEST_VAR", raising=False)
    assert env_str("HS_TEST_VAR", "d") == "d" and env_int("HS_TEST_INT", 7) == 7
    monkeypatch.setenv("HS_TEST_VAR", "")
    monkeypatch.setenv("HS_TEST_INT", "  ")
    assert env_str("HS_TEST_VAR", "d") == "d" and env_int("HS_TEST_INT", 7) == 7
    monkeypatch.setenv("HS_TEST_VAR", " set ")
    monkeypatch.setenv("HS_TEST_INT", " 12 ")
    assert env_str("HS_TEST_VAR", "d") == "set" and env_int("HS_TEST_INT", 7) == 12


# --- FallbackProvider: free first, Claude only when OpenRouter actually fails ---


def _fake_provider(name, model, fail_with=None, calls=None):
    from backend.agent.providers.base import LLMProvider, LLMResponse

    class _P(LLMProvider):
        key_source = "user"

        def create(self, system, transcript, tools, max_tokens):
            (calls if calls is not None else []).append(name)
            if fail_with is not None:
                raise fail_with
            return LLMResponse(text=f"from {name}", model=model)

        def stream(self, system, transcript, max_tokens, on_chunk):
            on_chunk("x")
            return self.create(system, transcript, [], max_tokens)

    p = _P()
    p.name, p.model = name, model
    return p


def _status_error(code):
    import httpx
    import openai

    response = httpx.Response(code, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    return openai.APIStatusError(f"status {code}", response=response, body=None)


def test_fallback_switches_on_a_rate_limit_and_stays_switched():
    calls = []
    primary = _fake_provider("openrouter", "free-model:free", fail_with=_status_error(429), calls=calls)
    fallback = _fake_provider("anthropic", "claude-haiku-4-5-20251001", calls=calls)
    provider = FallbackProvider(primary, fallback)

    first = provider.complete("hi", 100)
    assert first.text == "from anthropic" and provider.switched
    assert provider.name == "anthropic" and provider.model == "claude-haiku-4-5-20251001"
    assert "429" in (provider.fallback_reason or "")
    provider.complete("again", 100)
    assert calls == ["openrouter", "anthropic", "anthropic"], "after the switch the primary is never retried"


def test_fallback_does_not_hide_a_rejected_key():
    primary = _fake_provider("openrouter", "m:free", fail_with=_status_error(401))
    provider = FallbackProvider(primary, _fake_provider("anthropic", "claude-sonnet-5"))
    with pytest.raises(Exception, match="401"):
        provider.complete("hi", 100)
    assert not provider.switched


def test_fallback_is_transparent_while_the_primary_works():
    provider = FallbackProvider(_fake_provider("openrouter", "m:free"), _fake_provider("anthropic", "claude-sonnet-5"))
    assert provider.complete("hi", 100).text == "from openrouter"
    assert provider.name == "openrouter" and provider.model == "m:free" and not provider.switched


def test_openrouter_usage_reports_cached_prompt_tokens():
    from backend.agent.providers.openrouter_provider import _usage_dict

    usage = SimpleNamespace(prompt_tokens=1200, completion_tokens=50, prompt_tokens_details=SimpleNamespace(cached_tokens=1000))
    assert _usage_dict(usage) == {
        "input_tokens": 1200, "output_tokens": 50, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1000,
    }
    assert _usage_dict(None) == {}
    assert _usage_dict(SimpleNamespace(prompt_tokens=10, completion_tokens=1))["cache_read_input_tokens"] == 0


def test_openrouter_system_prompt_carries_a_cache_breakpoint():
    from backend.agent.providers.base import Transcript

    transcript = Transcript()
    transcript.add_user_text("q")
    messages = OpenRouterProvider._to_native_messages("SYSTEM", transcript)
    assert messages[0]["role"] == "system"
    assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert messages[1] == {"role": "user", "content": "q"}
