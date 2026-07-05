"""Guarded outbound HTTP fetch — the ONE blessed path for any future
feature that needs to fetch an arbitrary user-supplied URL. Not called by
any product path yet; this exists so the guard is already in place and
mechanically enforced (see test_llm_sdk_imports_confined_to_llm_package's
httpx-import restriction) before the first such feature is built, rather
than retrofitted after an SSRF incident.

Known limitation: resolution happens as a distinct check BEFORE the actual
request, which httpx then makes by re-resolving the hostname itself — a
DNS-rebinding attacker could theoretically swap the address between our
check and httpx's own connect. Fully closing that window means pinning the
connection to the checked IP via a custom transport while still using the
original hostname for TLS SNI/certificate validation, which is real
complexity not worth taking on before this function has an actual caller;
tighten this when the first URL-fetching feature lands.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

_ALLOWED_SCHEMES = {"http", "https"}
_DEFAULT_TIMEOUT_SECONDS = 10.0
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
# Cloud metadata endpoints (AWS/GCP/Azure/etc.) — not covered by
# ipaddress's private/loopback/link-local classification but exactly the
# kind of address SSRF exploits target.
_METADATA_IPS = {ipaddress.ip_address("169.254.169.254")}


class BlockedUrlError(ValueError):
    pass


def _default_resolver(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedUrlError(f"could not resolve host: {host}") from exc
    if not infos:
        raise BlockedUrlError(f"could not resolve host: {host}")
    return infos[0][4][0]


def _is_blocked_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    if ip in _METADATA_IPS:
        return True
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def _do_fetch(url: str, timeout_seconds: float, max_bytes: int) -> bytes:
    """The actual network call, separated out so tests can monkeypatch
    this one function instead of needing to mock httpx internals."""
    with httpx.Client(timeout=timeout_seconds) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise BlockedUrlError(f"response exceeded max size of {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks)


def guarded_fetch(
    url: str,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    resolver=_default_resolver,
) -> bytes:
    """Fetches url with SSRF protections: http/https scheme allowlist,
    resolves the host and rejects private/loopback/link-local/metadata
    addresses before making any request, and caps response size/timeout.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise BlockedUrlError(f"unsupported URL scheme: {parsed.scheme!r} (only http/https allowed)")
    if not parsed.hostname:
        raise BlockedUrlError("URL has no hostname")

    resolved_ip = resolver(parsed.hostname)
    if _is_blocked_ip(resolved_ip):
        raise BlockedUrlError(f"host {parsed.hostname} resolves to a disallowed address: {resolved_ip}")

    return _do_fetch(url, timeout_seconds, max_bytes)
