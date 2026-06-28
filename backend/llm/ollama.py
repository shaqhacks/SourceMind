"""OllamaProvider — wraps the ollama.chat API."""
from __future__ import annotations

import json


def _ollama_chat(**kwargs):
    """Lazy-imported ollama.chat call; patched in tests."""
    import ollama
    return ollama.chat(**kwargs)


class OllamaProvider:
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
        resp = _ollama_chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            format="json" if schema else None,
        )
        text = resp["message"]["content"]
        return json.loads(text) if schema else text
