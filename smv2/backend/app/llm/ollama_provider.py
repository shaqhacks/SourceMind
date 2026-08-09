"""Ollama-backed Provider — plain httpx against the Ollama HTTP API. No
`ollama` package dependency, deliberately: one fewer moving part, and the
chat/embeddings API surface is small enough that httpx directly is simpler.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from time import monotonic as _monotonic

import httpx

from app.config import embed_model, llm_model, ollama_base_url
from app.llm.completion_control import (
    CompletionOptions,
    CompletionPhase,
    CompletionProgress,
    ProviderCancelledError,
    ProviderStreamError,
)
from app.llm.provider import CompletionResult, Provider
from app.llm.retry import retry_transient

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_SECONDS = 15.0
_FIRST_ACTIVITY_TIMEOUT_SECONDS = 300.0
_INACTIVITY_TIMEOUT_SECONDS = 120.0
_HARD_TIMEOUT_SECONDS = 1800.0
_SUPERVISOR_TICK_SECONDS = 5.0


class OllamaProvider(Provider):
    supports_embeddings = True

    def __init__(self) -> None:
        self.model_name = llm_model()
        self.base_url = ollama_base_url()

    def _complete_impl(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        options: CompletionOptions,
        system: str | None = None,
    ) -> CompletionResult:
        full_messages = [{"role": "system", "content": system}, *messages] if system is not None else messages
        return asyncio.run(
            self._complete_stream(full_messages, max_tokens=max_tokens, options=options)
        )

    async def _complete_stream(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        options: CompletionOptions,
    ) -> CompletionResult:
        started = _monotonic()
        last_activity = started
        had_activity = False
        emitted_phases: set[CompletionPhase] = set()
        content_parts: list[str] = []
        usage = {"input": 0, "output": 0}

        def emit_progress(phase: CompletionPhase) -> None:
            if phase in emitted_phases:
                return
            emitted_phases.add(phase)
            if options.progress is None:
                return
            now = _monotonic()
            options.progress(
                CompletionProgress(
                    phase=phase,
                    elapsed_seconds=max(0.0, now - started),
                    seconds_since_activity=max(0.0, now - last_activity),
                )
            )

        def mark_activity(phase: CompletionPhase) -> None:
            nonlocal had_activity, last_activity
            had_activity = True
            last_activity = _monotonic()
            emit_progress(phase)

        def check_cancelled() -> None:
            if options.is_cancelled is not None and options.is_cancelled():
                raise ProviderCancelledError()

        def check_deadlines() -> None:
            now = _monotonic()
            if now - started >= _HARD_TIMEOUT_SECONDS:
                raise ProviderStreamError(
                    "Ollama stream exceeded the generation deadline.",
                    category="ollama_hard_wall_timeout",
                    had_activity=had_activity,
                )
            if had_activity:
                if now - last_activity >= _INACTIVITY_TIMEOUT_SECONDS:
                    raise ProviderStreamError(
                        "Ollama stream stopped producing updates.",
                        category="ollama_inactivity_timeout",
                        had_activity=True,
                    )
            elif now - started >= _FIRST_ACTIVITY_TIMEOUT_SECONDS:
                raise ProviderStreamError(
                    "Ollama stream did not start producing updates.",
                    category="ollama_first_activity_timeout",
                    had_activity=False,
                )

        check_cancelled()
        emit_progress("loading")
        payload: dict = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        if options.response_schema is not None:
            payload["format"] = options.response_schema

        timeout = httpx.Timeout(
            timeout=None,
            connect=_CONNECT_TIMEOUT_SECONDS,
            read=None,
            write=_CONNECT_TIMEOUT_SECONDS,
            pool=_CONNECT_TIMEOUT_SECONDS,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
                "POST", f"{self.base_url}/api/chat", json=payload
            ) as response:
                response.raise_for_status()
                await self._consume_lines(
                    response.aiter_lines(),
                    content_parts=content_parts,
                    mark_activity=mark_activity,
                    check_cancelled=check_cancelled,
                    check_deadlines=check_deadlines,
                    has_activity=lambda: had_activity,
                    set_usage=lambda prompt, eval_count: usage.update(
                        {"input": prompt, "output": eval_count}
                    ),
                )
        except ProviderCancelledError:
            raise
        except ProviderStreamError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ProviderStreamError(
                "Ollama stream could not connect.",
                category="ollama_connect_error",
                had_activity=had_activity,
            ) from None
        except httpx.HTTPStatusError as exc:
            category = (
                "ollama_transport_error"
                if exc.response is not None and exc.response.status_code >= 500
                else "ollama_model_error"
            )
            raise ProviderStreamError(
                "Ollama stream request failed.",
                category=category,
                had_activity=had_activity,
            ) from None
        except httpx.HTTPError:
            raise ProviderStreamError(
                "Ollama stream transport failed.",
                category="ollama_transport_error",
                had_activity=had_activity,
            ) from None

        text = "".join(content_parts)
        return CompletionResult(
            text=text,
            input_tokens=usage["input"],
            output_tokens=usage["output"],
            model=self.model_name,
        )

    async def _consume_lines(
        self,
        lines: AsyncIterator[str],
        *,
        content_parts: list[str],
        mark_activity,
        check_cancelled,
        check_deadlines,
        has_activity: Callable[[], bool],
        set_usage,
    ) -> None:
        pending_line: asyncio.Task[str] | None = asyncio.create_task(anext(lines))
        try:
            while pending_line is not None:
                check_cancelled()
                check_deadlines()
                done, _pending = await asyncio.wait(
                    {pending_line}, timeout=_SUPERVISOR_TICK_SECONDS
                )
                if not done:
                    continue
                try:
                    line = pending_line.result()
                except StopAsyncIteration:
                    raise ProviderStreamError(
                        "Ollama stream ended before a terminal chunk.",
                        category="ollama_transport_error",
                        had_activity=has_activity(),
                    ) from None

                terminal = self._handle_stream_line(
                    line,
                    content_parts,
                    mark_activity,
                    has_activity,
                    set_usage,
                )
                if terminal:
                    pending_line = None
                else:
                    pending_line = asyncio.create_task(anext(lines))
        finally:
            if pending_line is not None and not pending_line.done():
                pending_line.cancel()

    def _handle_stream_line(
        self,
        line: str,
        content_parts: list[str],
        mark_activity,
        has_activity: Callable[[], bool],
        set_usage,
    ) -> bool:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            raise ProviderStreamError(
                "Ollama stream returned a malformed chunk.",
                category="ollama_malformed_chunk",
                had_activity=has_activity(),
            ) from None

        if not isinstance(data, dict):
            raise ProviderStreamError(
                "Ollama stream returned a malformed chunk.",
                category="ollama_malformed_chunk",
                had_activity=has_activity(),
            )
        if "error" in data:
            raise ProviderStreamError(
                "Ollama model reported a generation error.",
                category="ollama_model_error",
                had_activity=has_activity(),
            )

        message = data.get("message")
        done = data.get("done", False)
        if not isinstance(done, bool):
            raise ProviderStreamError(
                "Ollama stream returned a malformed chunk.",
                category="ollama_malformed_chunk",
                had_activity=has_activity(),
            )
        if message is None and not done:
            raise ProviderStreamError(
                "Ollama stream returned a malformed chunk.",
                category="ollama_malformed_chunk",
                had_activity=has_activity(),
            )

        if message is not None:
            if not isinstance(message, dict):
                raise ProviderStreamError(
                    "Ollama stream returned a malformed chunk.",
                    category="ollama_malformed_chunk",
                    had_activity=has_activity(),
                )
            if "thinking" in message:
                thinking = message["thinking"]
                if not isinstance(thinking, str):
                    raise ProviderStreamError(
                        "Ollama stream returned a malformed chunk.",
                        category="ollama_malformed_chunk",
                        had_activity=has_activity(),
                    )
                mark_activity("thinking")
            if "content" in message:
                content = message["content"]
                if not isinstance(content, str):
                    raise ProviderStreamError(
                        "Ollama stream returned a malformed chunk.",
                        category="ollama_malformed_chunk",
                        had_activity=has_activity(),
                    )
                content_parts.append(content)
                if content or "thinking" not in message:
                    mark_activity("generating")
            if "thinking" not in message and "content" not in message and not done:
                raise ProviderStreamError(
                    "Ollama stream returned a malformed chunk.",
                    category="ollama_malformed_chunk",
                    had_activity=has_activity(),
                )

        if done:
            prompt_count = data.get("prompt_eval_count", 0)
            eval_count = data.get("eval_count", 0)
            if not isinstance(prompt_count, int) or not isinstance(eval_count, int):
                raise ProviderStreamError(
                    "Ollama stream returned a malformed chunk.",
                    category="ollama_malformed_chunk",
                    had_activity=has_activity(),
                )
            set_usage(prompt_count, eval_count)
            mark_activity("finalizing")
            return True
        return False

    def _embed_impl(self, texts: list[str]) -> list[list[float] | None]:
        """One request per text, sharing the same transient-retry policy as
        complete(). Per-item isolation: a failure on one text (even after
        its own retry) leaves that entry None rather than failing the
        whole batch — callers (embed_course) treat that chunk as still
        unembedded and move on.
        """
        model = embed_model()
        results: list[list[float] | None] = []
        for text in texts:
            try:
                results.append(retry_transient(lambda t=text: self._embed_one(t, model)))
            except Exception:
                logger.exception("embedding failed for one text; leaving it null")
                results.append(None)
        return results

    def _embed_one(self, text: str, model: str) -> list[float]:
        response = httpx.post(
            f"{self.base_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=_INACTIVITY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        return data["embedding"]
