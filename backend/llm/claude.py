"""ClaudeProvider — wraps Anthropic's messages API."""
from __future__ import annotations

from SourceMind.backend.llm._timeout import call_with_timeout_retry, llm_timeout


def _get_anthropic():
    """Lazy import of anthropic.Anthropic class; patched in tests."""
    import anthropic
    return anthropic.Anthropic


class ClaudeProvider:
    def __init__(self, model: str) -> None:
        self.model = model

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> str | dict:
        Anthropic = _get_anthropic()
        client = Anthropic()
        timeout = llm_timeout()

        if schema is not None:
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
