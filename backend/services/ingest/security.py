"""Security guards for network-sourced ingestion (T9).

Two distinct threats are handled here:

* **SSRF** — before any URL/YouTube fetch, :func:`validate_public_url` rejects
  non-http(s) schemes, embedded credentials, and hosts that resolve to private,
  loopback, link-local (incl. the cloud metadata endpoint), or otherwise
  non-public addresses. The fetcher MUST call this first.
* **Prompt injection** — fetched third-party content can contain instructions
  aimed at the downstream LLM ("ignore previous instructions", "reveal your
  system prompt"). :func:`sanitize_source` strips those imperative lines before
  the text is ever handed to a model.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Callable
from urllib.parse import urlparse

from SourceMind.backend.services.ingest.base import IngestError


class SsrfError(IngestError):
    """A URL points at a non-public / disallowed destination."""


_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
_BLOCKED_HOST_NAMES = {"localhost"}


def _ip_literal(host: str) -> ipaddress._BaseAddress | None:
    """Parse a host as an IP literal, including non-canonical IPv4 encodings
    (integer ``2130706433``, hex ``0x7f000001``, octal ``0177.0.0.1``) so they
    cannot slip past the range checks. Returns None for real hostnames."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.inet_aton(host))  # decimal/hex/octal IPv4 forms
    except OSError:
        return None


def validate_public_url(url: str, *, resolver: Callable[[str], list[str]] | None = None) -> str:
    """Return ``url`` if it is safe to fetch, else raise :class:`SsrfError`.

    Blocks non-http(s) schemes, embedded credentials, internal hostnames, and any
    host that is (or resolves to) a private/loopback/link-local/reserved address.
    Non-canonical IPv4 encodings are normalized before checking. ``resolver``
    (hostname -> IP strings) is injectable; a caller that actually fetches MUST
    additionally re-run this on the FINAL URL after each redirect hop, since this
    function validates only the URL it is given.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfError(f"Only http(s) URLs may be fetched, not {parsed.scheme!r}.")
    if parsed.username or parsed.password:
        raise SsrfError("URLs with embedded credentials are not allowed.")
    host = parsed.hostname
    if not host:
        raise SsrfError("URL has no host.")

    host = host.rstrip(".")  # trailing-dot FQDNs resolve the same as without
    lowered = host.lower()
    if lowered in _BLOCKED_HOST_NAMES or lowered.endswith(_BLOCKED_HOST_SUFFIXES):
        raise SsrfError(f"Refusing to fetch internal host {host!r}.")

    candidate_ips: list[ipaddress._BaseAddress] = []
    literal = _ip_literal(host)
    if literal is not None:
        candidate_ips.append(literal)
    elif resolver is not None:
        # Fail closed: a DNS failure or a non-IP result must block, not leak a
        # gaierror/ValueError out of the SSRF guard.
        try:
            candidate_ips.extend(ipaddress.ip_address(addr) for addr in resolver(host))
        except Exception as exc:
            raise SsrfError(f"Could not safely resolve host {host!r}: {exc}") from exc

    for ip in candidate_ips:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local  # includes 169.254.169.254 metadata endpoint
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SsrfError(f"Refusing to fetch non-public address {ip}.")
    return url


# Sentences/lines that look like attempts to steer the downstream model.
# A best-effort defense-in-depth filter, NOT a security boundary: the LLM prompt
# should also fence untrusted content with clear instruction-priority framing.
_INJECTION_PATTERNS = [
    re.compile(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|what|the)\b"
               r".{0,40}(instructions?|prompts?|rules?|context|told|said)", re.IGNORECASE),
    re.compile(r"\b(reveal|print|repeat|show|output|give)\b.{0,40}\b(system|developer|initial)\b.{0,20}prompt", re.IGNORECASE),
    re.compile(r"\b(you are now|act as|pretend to be|developer mode|jailbreak|do anything now|DAN)\b", re.IGNORECASE),
    re.compile(r"\b(new rule|from now on|you must now|instead (?:you|please)|your new (?:task|instruction))\b", re.IGNORECASE),
    re.compile(r"^\s*(system|assistant|user)\s*:", re.IGNORECASE),  # role-marker injection, anchored to unit start
]

# Within a line, split into sentences on terminal punctuation.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _is_injection(unit: str) -> bool:
    return any(pattern.search(unit) for pattern in _INJECTION_PATTERNS)


def _line_sentences(line: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(line) if s.strip()]


def scan_for_prompt_injection(text: str) -> list[str]:
    """Return the sentences/lines of ``text`` that look like prompt injection."""
    findings: list[str] = []
    for line in (text or "").split("\n"):
        for sentence in _line_sentences(line):
            if _is_injection(sentence):
                findings.append(sentence.strip())
    return findings


def sanitize_source(text: str) -> tuple[str, list[str]]:
    """Strip prompt-injection sentences from ``text``, preserving line structure.

    Newlines are kept (downstream outline detection relies on them); only the
    offending sentences are removed. Returns ``(clean_text, findings)``.
    """
    findings: list[str] = []
    kept_lines: list[str] = []
    for line in (text or "").split("\n"):
        kept_sentences: list[str] = []
        for sentence in _line_sentences(line):
            if _is_injection(sentence):
                findings.append(sentence.strip())
            else:
                kept_sentences.append(sentence.strip())
        kept_lines.append(" ".join(kept_sentences))
    return "\n".join(kept_lines), findings
