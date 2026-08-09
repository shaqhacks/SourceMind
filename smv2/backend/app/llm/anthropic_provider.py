"""Anthropic-backed Provider. Only this module (and ollama_provider.py) is
allowed to import the anthropic/httpx-to-ollama SDKs — see
test_llm_sdk_imports_confined_to_llm_package.
"""

from __future__ import annotations

import time

import anthropic

from app.config import anthropic_api_key, llm_model
from app.llm.completion_control import (
    CompletionOptions,
    CompletionPhase,
    CompletionProgress,
    ProviderCancelledError,
)
from app.llm.provider import (
    PROVIDER_NOT_CONFIGURED_MESSAGE,
    CompletionResult,
    NotSupportedError,
    Provider,
    ProviderNotConfiguredError,
)


def _is_missing_credentials_error(exc: Exception) -> bool:
    """True for the ways this SDK signals "no usable credentials at all" —
    both a real 401/403 from the API (a key was sent but rejected) and the
    client-side failure when no api_key/auth_token/credentials resolve from
    any source (env, profile, federation) before a request is even sent.
    That second case is, as of this SDK version, a bare TypeError rather
    than an AnthropicError subclass — matched narrowly on its message so an
    unrelated TypeError elsewhere in this call is never misclassified.
    """
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return True
    return isinstance(exc, TypeError) and "authentication method" in str(exc).lower()


class AnthropicProvider(Provider):
    supports_embeddings = False  # explicit: matches the base default, but this is the provider that actually raises

    def __init__(self) -> None:
        self.model_name = llm_model()
        # max_retries=0: the SDK defaults to retrying transient errors itself,
        # which would compound with app.llm.retry's own retry_transient() and
        # violate "one retry mechanism, never double-retry" — retry.py is the
        # sole retry authority for every provider.
        #
        # anthropic_api_key() already resolves ANTHROPIC_API_KEY > secrets.toml
        # > None; passing api_key=None here is not a special case worth
        # branching on — the SDK's own default for this parameter is None,
        # and it does the identical os.environ.get("ANTHROPIC_API_KEY")
        # fallback internally when it sees one, so precedence is preserved
        # either way (verified against the installed SDK's __init__ source).
        self._client = anthropic.Anthropic(api_key=anthropic_api_key(), max_retries=0)

    def _complete_impl(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        options: CompletionOptions,
        system: str | None = None,
    ) -> CompletionResult:
        started = time.monotonic()

        def _emit_progress(phase: CompletionPhase) -> None:
            if options.progress is None:
                return
            elapsed_seconds = max(0.0, time.monotonic() - started)
            options.progress(
                CompletionProgress(
                    phase=phase, elapsed_seconds=elapsed_seconds, seconds_since_activity=0.0
                )
            )

        if options.is_cancelled is not None and options.is_cancelled():
            raise ProviderCancelledError()
        _emit_progress("loading")
        kwargs: dict = {"model": self.model_name, "max_tokens": max_tokens, "messages": messages}
        if system is not None:
            kwargs["system"] = system
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:
            if _is_missing_credentials_error(exc):
                raise ProviderNotConfiguredError(PROVIDER_NOT_CONFIGURED_MESSAGE) from exc
            raise
        text = "".join(block.text for block in response.content if block.type == "text")
        _emit_progress("finalizing")
        return CompletionResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )

    def _embed_impl(self, texts: list[str]) -> list[list[float] | None]:
        raise NotSupportedError("Anthropic has no embeddings API")
