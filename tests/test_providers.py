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


def test_both_keys_run_on_claude_with_openrouter_as_the_fallback(monkeypatch):
    """Claude writes the report; the free path stays as a safety net for a
    rate limit or an outage on the Anthropic side."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "local-dev-openrouter")
    provider = get_provider({"ANTHROPIC_API_KEY": "user-anthropic-key"})
    assert isinstance(provider, FallbackProvider)
    assert isinstance(provider.primary, AnthropicProvider) and isinstance(provider.fallback, OpenRouterProvider)
    assert provider.name == "anthropic" and not provider.switched
    assert provider.primary.key_source == "user" and provider.fallback.key_source == "platform"


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
    assert fast.model == "claude-haiku-4-5"


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


def _fake_provider(name, model, fail_with=None, calls=None, response=None):
    from backend.agent.providers.base import LLMProvider, LLMResponse

    class _P(LLMProvider):
        key_source = "user"

        def create(self, system, transcript, tools, max_tokens):
            (calls if calls is not None else []).append(name)
            if fail_with is not None:
                raise fail_with
            return response if response is not None else LLMResponse(text=f"from {name}", model=model)

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
    fallback = _fake_provider("anthropic", "claude-haiku-4-5", calls=calls)
    provider = FallbackProvider(primary, fallback)

    first = provider.complete("hi", 100)
    assert first.text == "from anthropic" and provider.switched
    assert provider.name == "anthropic" and provider.model == "claude-haiku-4-5"
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


# --- An empty completion is a failure too, not a successful turn ---


def test_a_completion_with_no_text_and_no_tool_calls_triggers_the_fallback():
    """The free path's real failure mode is a 200 OK with nothing in it —
    reasoning-only output, or a truncation before any content. That is not
    an exception, so it used to sail straight through to the report."""
    from backend.agent.providers.base import LLMResponse

    calls = []
    primary = _fake_provider("openrouter", "m:free", calls=calls, response=LLMResponse(text="   ", model="m:free"))
    fallback = _fake_provider("anthropic", "claude-sonnet-5", calls=calls)
    provider = FallbackProvider(primary, fallback)

    assert provider.complete("write the report", 100).text == "from anthropic"
    assert provider.switched and "empty" in (provider.fallback_reason or "").lower()
    assert calls == ["openrouter", "anthropic"]


def test_a_tool_call_turn_with_no_text_is_not_treated_as_empty():
    """A normal tool-use turn carries no prose. Falling back on that would
    switch providers on nearly every ACT turn."""
    from backend.agent.providers.base import LLMResponse, ToolCall, Transcript

    calls = []
    tool_turn = LLMResponse(
        text="", tool_calls=[ToolCall(id="c1", name="pubmed", input={})], stop_reason="tool_use", model="m:free"
    )
    provider = FallbackProvider(
        _fake_provider("openrouter", "m:free", calls=calls, response=tool_turn),
        _fake_provider("anthropic", "claude-sonnet-5", calls=calls),
    )
    result = provider.create("sys", Transcript(), [], 100)
    assert result.tool_calls and not provider.switched
    assert calls == ["openrouter"]


def test_the_fallback_returning_empty_is_not_an_infinite_loop():
    from backend.agent.providers.base import LLMResponse

    calls = []
    empty = LLMResponse(text="", model="x")
    provider = FallbackProvider(
        _fake_provider("openrouter", "m:free", calls=calls, response=empty),
        _fake_provider("anthropic", "claude-sonnet-5", calls=calls, response=empty),
    )
    assert provider.complete("hi", 100).text == ""
    assert calls == ["openrouter", "anthropic"], "each provider is tried at most once"


# --- OpenRouter streaming: reasoning, tool calls and the real finish reason ---


def _chunk(content=None, reasoning=None, finish_reason=None, tool_calls=None, model="m:free", usage=None):
    delta = SimpleNamespace(content=content, reasoning=reasoning, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(model=model, choices=[choice], usage=usage)


def _streaming_provider(chunks):
    provider = OpenRouterProvider(api_key="k", model="m:free")
    provider._call_with_retry = lambda **kwargs: iter(chunks)  # type: ignore[method-assign]
    return provider


def test_stream_falls_back_to_reasoning_when_no_content_arrives():
    """Several free models stream their answer into `reasoning` and leave
    `content` empty — that used to be reported as an empty response."""
    from backend.agent.providers.base import Transcript

    provider = _streaming_provider([
        _chunk(reasoning="Weighing the evidence. "),
        _chunk(reasoning="SIRT1 activation is plausible."),
        _chunk(finish_reason="stop"),
    ])
    seen: list[str] = []
    response = provider.stream("sys", Transcript(), 100, seen.append)
    assert "SIRT1 activation is plausible." in response.text
    assert seen, "the status bar still gets something to show"


def test_stream_prefers_content_over_reasoning_when_both_arrive():
    from backend.agent.providers.base import Transcript

    provider = _streaming_provider([
        _chunk(reasoning="thinking out loud"),
        _chunk(content="## Hypothesis"),
        _chunk(content="\n\nThe real answer.", finish_reason="stop"),
    ])
    response = provider.stream("sys", Transcript(), 100, lambda _: None)
    assert response.text == "## Hypothesis\n\nThe real answer."
    assert "thinking out loud" not in response.text


def test_stream_reports_the_real_finish_reason():
    from backend.agent.providers.base import Transcript

    provider = _streaming_provider([_chunk(content="cut off here", finish_reason="length")])
    assert provider.stream("sys", Transcript(), 100, lambda _: None).stop_reason == "length"


def test_stream_accumulates_tool_call_deltas():
    from backend.agent.providers.base import Transcript

    provider = _streaming_provider([
        _chunk(tool_calls=[SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="pubmed", arguments='{"que'))]),
        _chunk(tool_calls=[SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='ry": "sirt1"}'))]),
        _chunk(finish_reason="tool_calls"),
    ])
    response = provider.stream("sys", Transcript(), 100, lambda _: None)
    assert [(c.id, c.name, c.input) for c in response.tool_calls] == [("call_1", "pubmed", {"query": "sirt1"})]
    assert response.stop_reason == "tool_use"


def test_a_400_on_the_cache_control_shape_retries_once_without_it():
    """Caching is an optimization. If an upstream rejects the content-part
    array that carries cache_control, the run continues uncached rather than
    dying — this path cannot be exercised against a live key here, so the
    safety net is asserted directly."""
    import httpx
    import openai

    from backend.agent.providers.base import Transcript

    sent: list[list[dict]] = []

    def _create(**kwargs):
        sent.append(kwargs["messages"])
        if len(sent) == 1:
            response = httpx.Response(400, request=httpx.Request("POST", "https://openrouter.ai/api/v1/x"))
            raise openai.BadRequestError("invalid content part", response=response, body=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
            usage=None,
            model="m:free",
        )

    provider = OpenRouterProvider(api_key="k", model="m:free")
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    transcript = Transcript()
    transcript.add_user_text("q")

    assert provider.create("SYSTEM", transcript, [], 100).text == "ok"
    assert len(sent) == 2, "exactly one retry"
    assert isinstance(sent[0][0]["content"], list), "the first attempt carried the cache breakpoint"
    assert sent[1][0]["content"] == "SYSTEM", "the retry sent a plain string"


def test_a_400_unrelated_to_cache_control_is_not_retried():
    import httpx
    import openai

    from backend.agent.providers.base import Transcript

    calls = []

    def _create(**kwargs):
        calls.append(kwargs)
        response = httpx.Response(400, request=httpx.Request("POST", "https://openrouter.ai/api/v1/x"))
        raise openai.BadRequestError("model does not exist", response=response, body=None)

    provider = OpenRouterProvider(api_key="k", model="m:free")
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    transcript = Transcript()
    transcript.add_user_text("q")

    with pytest.raises(openai.BadRequestError):
        provider.create("", transcript, [], 100)  # no system prompt -> no content-part array
    assert len(calls) == 1
