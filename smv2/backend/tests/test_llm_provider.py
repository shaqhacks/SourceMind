from __future__ import annotations

from app.db.engine import get_session
from app.db.models import LlmCall


def test_successful_call_writes_ok_ledger_row(client, stub_provider):
    course_id = client.post("/api/courses", json={"title": "Ledger Test Course"}).json()["id"]

    result = stub_provider.complete(
        [{"role": "user", "content": "hello"}],
        max_tokens=100,
        purpose="lesson",
        course_id=course_id,
        prompt_version="v1",
    )

    assert result.text == "stub lesson content"

    session = get_session()
    try:
        rows = session.query(LlmCall).filter(LlmCall.course_id == course_id).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "ok"
        assert row.purpose == "lesson"
        assert row.model == "stub-model"
        assert row.input_tokens == 100
        assert row.output_tokens == 200
        assert row.prompt_version == "v1"
        assert row.latency_ms >= 0
    finally:
        session.close()


def test_failed_call_writes_error_ledger_row_and_reraises(client, stub_provider):
    course_id = client.post("/api/courses", json={"title": "Ledger Error Test Course"}).json()["id"]
    stub_provider.exceptions = [RuntimeError("boom")]

    try:
        stub_provider.complete(
            [{"role": "user", "content": "hello"}],
            max_tokens=100,
            purpose="lesson",
            course_id=course_id,
        )
        raised = False
    except RuntimeError:
        raised = True

    assert raised is True

    session = get_session()
    try:
        rows = session.query(LlmCall).filter(LlmCall.course_id == course_id).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "error"
        assert row.cost_estimate is None
        assert row.input_tokens == 0
        assert row.output_tokens == 0
    finally:
        session.close()


def test_get_provider_returns_anthropic_by_default(client, monkeypatch):
    from app.llm.provider import get_provider

    monkeypatch.setenv("SMV2_LLM_PROVIDER", "anthropic")
    provider = get_provider()
    assert type(provider).__name__ == "AnthropicProvider"


def test_get_provider_returns_ollama_when_configured(client, monkeypatch):
    from app.llm.provider import get_provider

    monkeypatch.setenv("SMV2_LLM_PROVIDER", "ollama")
    provider = get_provider()
    assert type(provider).__name__ == "OllamaProvider"


def test_get_provider_rejects_unknown_backend(client, monkeypatch):
    import pytest

    from app.llm.provider import get_provider

    monkeypatch.setenv("SMV2_LLM_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError):
        get_provider()


def test_embed_base_class_default_is_none_per_text(client):
    """A provider that doesn't override _embed_impl at all (the base
    class's own default) returns None per text — this is what
    AnthropicProvider would fall back to if it didn't explicitly raise
    NotSupportedError instead (see test_anthropic_provider_embed_raises_not_supported).
    """
    from app.llm.provider import Provider

    class _NoEmbedProvider(Provider):
        model_name = "no-embed-stub"

        def _complete_impl(self, messages, *, max_tokens, system=None):
            raise NotImplementedError

    result = _NoEmbedProvider().embed(["a", "b", "c"])
    assert result == [None, None, None]


def test_stub_provider_embed_returns_real_vectors_by_default(client, stub_provider):
    """StubProvider overrides _embed_impl with a real (fixed) vector per
    text by default, so Phase 4 tests exercising embed_course/retrieval
    don't all need to configure embed_responses explicitly.
    """
    result = stub_provider.embed(["a", "b", "c"])
    assert result == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    assert stub_provider.embed_call_count == 1
    assert stub_provider.received_embed_texts == [["a", "b", "c"]]


def test_ledger_write_failure_does_not_destroy_a_successful_completion(client, stub_provider, monkeypatch):
    """Regression: the caller already "paid for" this completion (a real
    API call happened) — a broken ledger write must not turn that into an
    exception and lose the result.
    """
    def _boom(**kwargs):
        raise RuntimeError("ledger write exploded")

    monkeypatch.setattr("app.llm.provider.record_llm_call", _boom)

    result = stub_provider.complete(
        [{"role": "user", "content": "hello"}], max_tokens=100, purpose="lesson"
    )

    assert result.text == "stub lesson content"


def test_ledger_write_failure_does_not_mask_the_original_provider_error(client, stub_provider, monkeypatch):
    """Regression: on the failure path, a broken ledger write must not
    replace the ORIGINAL provider exception with the ledger's own.
    """
    def _boom(**kwargs):
        raise RuntimeError("ledger write exploded")

    monkeypatch.setattr("app.llm.provider.record_llm_call", _boom)
    stub_provider.exceptions = [ValueError("original provider failure")]

    import pytest

    with pytest.raises(ValueError, match="original provider failure"):
        stub_provider.complete([{"role": "user", "content": "hello"}], max_tokens=100, purpose="lesson")


def test_anthropic_provider_sends_system_separately_from_messages(monkeypatch):
    from app.llm.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("SMV2_LLM_MODEL", "claude-sonnet-5")
    provider = AnthropicProvider()

    captured: dict = {}

    class _FakeUsage:
        input_tokens = 10
        output_tokens = 20

    class _FakeBlock:
        type = "text"
        text = "a response"

    class _FakeResponse:
        content = [_FakeBlock()]
        usage = _FakeUsage()
        model = "claude-sonnet-5"

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeResponse()

    provider._client.messages.create = _fake_create

    result = provider._complete_impl(
        [{"role": "user", "content": "hello"}], max_tokens=100, system="be a helpful teacher"
    )

    assert captured["system"] == "be a helpful teacher"
    assert captured["messages"] == [{"role": "user", "content": "hello"}]
    assert result.text == "a response"


def test_anthropic_provider_omits_system_kwarg_when_not_given(monkeypatch):
    from app.llm.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("SMV2_LLM_MODEL", "claude-sonnet-5")
    provider = AnthropicProvider()
    captured: dict = {}

    class _FakeUsage:
        input_tokens = 1
        output_tokens = 1

    class _FakeBlock:
        type = "text"
        text = "ok"

    class _FakeResponse:
        content = [_FakeBlock()]
        usage = _FakeUsage()
        model = "claude-sonnet-5"

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeResponse()

    provider._client.messages.create = _fake_create
    provider._complete_impl([{"role": "user", "content": "hi"}], max_tokens=10)

    assert "system" not in captured


def test_anthropic_provider_missing_credentials_raises_friendly_error(monkeypatch):
    """As of the installed SDK version, calling messages.create() with no
    api_key/auth_token/credentials resolved from any source raises a bare
    TypeError (not an AnthropicError subclass) before any request is sent —
    this pins that real SDK behavior and asserts _complete_impl translates
    it into the friendly, actionable ProviderNotConfiguredError rather than
    letting the raw SDK message reach job.error or a chat response.
    """
    import pytest

    from app.llm.anthropic_provider import AnthropicProvider
    from app.llm.provider import PROVIDER_NOT_CONFIGURED_MESSAGE, ProviderNotConfiguredError

    monkeypatch.setenv("SMV2_LLM_MODEL", "claude-sonnet-5")
    provider = AnthropicProvider()

    def _fake_create(**kwargs):
        raise TypeError(
            "Could not resolve authentication method. Expected one of api_key, "
            "auth_token, or credentials to be set."
        )

    provider._client.messages.create = _fake_create

    with pytest.raises(ProviderNotConfiguredError) as exc_info:
        provider._complete_impl([{"role": "user", "content": "hi"}], max_tokens=10)
    assert str(exc_info.value) == PROVIDER_NOT_CONFIGURED_MESSAGE


def test_anthropic_provider_uses_key_from_secrets_toml_when_env_absent(tmp_path, monkeypatch):
    """No ANTHROPIC_API_KEY in the environment at all -- the provider must
    still pick up a key from data/secrets.toml rather than constructing an
    unconfigured client.
    """
    from app.llm.anthropic_provider import AnthropicProvider

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SMV2_LLM_MODEL", "claude-sonnet-5")
    (tmp_path / "secrets.toml").write_text('anthropic_api_key = "sk-from-secrets-file"\n')

    provider = AnthropicProvider()
    assert provider._client.api_key == "sk-from-secrets-file"


def test_anthropic_provider_env_key_wins_over_secrets_toml(tmp_path, monkeypatch):
    from app.llm.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SMV2_LLM_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    (tmp_path / "secrets.toml").write_text('anthropic_api_key = "sk-from-secrets-file"\n')

    provider = AnthropicProvider()
    assert provider._client.api_key == "sk-from-env"


def test_anthropic_provider_authentication_error_raises_friendly_error(monkeypatch):
    """A real 401 (a key was sent but rejected) must map to the same
    friendly error as the no-credentials-at-all case above.
    """
    import anthropic
    import httpx
    import pytest

    from app.llm.anthropic_provider import AnthropicProvider
    from app.llm.provider import PROVIDER_NOT_CONFIGURED_MESSAGE, ProviderNotConfiguredError

    monkeypatch.setenv("SMV2_LLM_MODEL", "claude-sonnet-5")
    provider = AnthropicProvider()

    def _fake_create(**kwargs):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(401, request=request, json={"error": {"message": "invalid x-api-key"}})
        raise anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)

    provider._client.messages.create = _fake_create

    with pytest.raises(ProviderNotConfiguredError) as exc_info:
        provider._complete_impl([{"role": "user", "content": "hi"}], max_tokens=10)
    assert str(exc_info.value) == PROVIDER_NOT_CONFIGURED_MESSAGE


def test_ollama_provider_prepends_system_as_its_own_message(monkeypatch):
    import httpx

    from app.llm.ollama_provider import OllamaProvider

    monkeypatch.setenv("SMV2_LLM_MODEL", "some-ollama-model")
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://fake-ollama:11434")
    provider = OllamaProvider()

    captured: dict = {}

    def _fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"message": {"content": "hi there"}, "prompt_eval_count": 5, "eval_count": 7},
            request=request,
        )

    monkeypatch.setattr("app.llm.ollama_provider.httpx.post", _fake_post)

    result = provider._complete_impl(
        [{"role": "user", "content": "hello"}], max_tokens=50, system="be a helpful teacher"
    )

    sent_messages = captured["json"]["messages"]
    assert sent_messages[0] == {"role": "system", "content": "be a helpful teacher"}
    assert sent_messages[1] == {"role": "user", "content": "hello"}
    assert result.text == "hi there"
