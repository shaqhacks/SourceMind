"""ClaudeProvider — wraps Anthropic's messages API."""
from __future__ import annotations

from SourceMind.backend.llm._timeout import call_with_timeout_retry, llm_timeout
from SourceMind.backend.llm.limiter import llm_slot


def _get_anthropic():
    """Lazy import of anthropic.Anthropic class; patched in tests."""
    import anthropic
    return anthropic.Anthropic


class ClaudeProvider:
    def __init__(self, model: str) -> None:
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazily construct and cache the Anthropic client for this instance.

        Constructing ``Anthropic()`` opens an HTTP connection pool; building a
        fresh one on every ``complete()`` call threw that away each time. The
        client is stateless w.r.t. the per-call ``timeout`` (passed to
        ``messages.create`` below), so one instance is safe to reuse for the
        lifetime of this provider.
        """
        if self._client is None:
            Anthropic = _get_anthropic()
            self._client = Anthropic()
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> str | dict:
        client = self._get_client()
        timeout = llm_timeout()

        if schema is not None:
            with llm_slot():
                resp = call_with_timeout_retry(
                    lambda: client.messages.create(
                        model=self.model,
                        max_tokens=max_tokens,
                        system=system,
                        messages=[{"role": "user", "content": prompt}],
                        tools=[
                            {
                                "name": "emit",
                                "description": "Return the structured result.",
                                "input_schema": schema,
                            }
                        ],
                        tool_choice={"type": "tool", "name": "emit"},
                        timeout=timeout,
                    )
                )
            for block in resp.content:
                if block.type == "tool_use":
                    return block.input
            return {}

        with llm_slot():
            resp = call_with_timeout_retry(
                lambda: client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=timeout,
                )
            )
        return "".join(b.text for b in resp.content if b.type == "text")
