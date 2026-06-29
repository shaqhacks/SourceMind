"""OllamaProvider — wraps the ollama.chat API.

Hardened for local models that (a) wrap reasoning in <think>...</think>
blocks (e.g. the Qwen3 family), (b) occasionally fence JSON in ```json
blocks, or (c) surround JSON with prose. When a schema is requested we pass
it to Ollama's structured-output `format` so the grammar is constrained, then
parse defensively.
"""
from __future__ import annotations

import json
import os
import re

from SourceMind.backend.llm._timeout import call_with_timeout_retry

_DEFAULT_NUM_CTX = 16384


def _num_ctx() -> int:
    """Context-window size for Ollama. Default is small (~4k) and silently
    truncates long inputs, so we raise it (env-overridable)."""
    try:
        return int(os.environ.get("SOURCEMIND_OLLAMA_NUM_CTX", _DEFAULT_NUM_CTX))
    except (TypeError, ValueError):
        return _DEFAULT_NUM_CTX

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_]*\s*\n?|\n?```$", re.MULTILINE)


def _ollama_chat(**kwargs):
    """Lazy-imported ollama.chat call; patched in tests."""
    import ollama
    return ollama.chat(**kwargs)


def _chat(**kwargs):
    """Call ollama.chat, disabling 'thinking' so reasoning models (Qwen3, etc.)
    emit a real answer instead of spending the token budget on <think> and
    returning empty content. Falls back if the client doesn't support `think`."""
    try:
        return _ollama_chat(think=False, **kwargs)
    except TypeError:
        return _ollama_chat(**kwargs)


def _strip_think(text: str) -> str:
    """Remove <think>...</think> reasoning blocks emitted by thinking models."""
    return _THINK_RE.sub("", text or "").strip()


def _json_span(text: str) -> str | None:
    """Return the substring from the first opening bracket to its match, or None."""
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    if start == -1:
        return None
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    for i in range(start, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _extract_objects(text: str, start: int) -> list:
    """Extract consecutive complete JSON objects beginning at *start* (just after
    a ``[``). Stops at the first incomplete/truncated object."""
    objs: list = []
    i, n = start, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == "]" or text[i] != "{":
            break
        depth, j, in_str, esc, ok = 0, i, False, False, False
        while j < n:
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    ok = True
                    j += 1
                    break
            j += 1
        if not ok:
            break  # truncated object — stop here
        try:
            objs.append(json.loads(text[i:j]))
        except json.JSONDecodeError:
            break
        i = j
    return objs


def _salvage_array(text: str):
    """Recover a (possibly truncated) array of objects — e.g. when the model's
    JSON was cut off mid-element because it hit the token limit. Returns
    ``{key: [objs]}`` for a named array property, a bare ``[objs]`` for a
    top-level array, or ``None`` if nothing usable was found."""
    start = text.find("[")
    if start == -1:
        return None
    objs = _extract_objects(text, start + 1)
    if not objs:
        return None
    prefix = text[:start].rstrip()
    m = re.search(r'"([A-Za-z0-9_]+)"\s*:\s*$', prefix)
    if m:
        return {m.group(1): objs}
    return objs


def _parse_json(raw: str) -> dict | list:
    """Parse JSON from a (possibly noisy) model response."""
    text = _strip_think(raw)
    if not text:
        raise ValueError(
            "Ollama returned empty output for a structured (JSON) request — "
            "the model may not support structured output, or num_predict is too low."
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown code fences and retry.
    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Extract the first balanced JSON span.
    span = _json_span(cleaned)
    if span is not None:
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            pass
    # Salvage complete objects from a truncated array (model hit the token limit).
    salvaged = _salvage_array(cleaned)
    if salvaged is not None:
        return salvaged
    raise ValueError(f"Could not parse JSON from Ollama response: {text[:200]!r}")


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
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            options={"num_predict": max_tokens, "num_ctx": _num_ctx()},
        )
        if schema:
            # Pass the JSON schema directly so Ollama constrains output to it
            # (structured outputs) — far more reliable than format="json".
            kwargs["format"] = schema
        resp = call_with_timeout_retry(lambda: _chat(**kwargs))
        text = resp["message"]["content"]
        if schema:
            return _parse_json(text)
        # Non-schema (e.g. chapter prose): strip any leaked reasoning block.
        return _strip_think(text)
