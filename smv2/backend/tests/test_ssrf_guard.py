from __future__ import annotations

import pytest

from app.security.fetch import BlockedUrlError, _is_blocked_ip, guarded_fetch


def test_file_scheme_rejected():
    with pytest.raises(BlockedUrlError, match="scheme"):
        guarded_fetch("file:///etc/passwd")


def test_ftp_scheme_rejected():
    with pytest.raises(BlockedUrlError, match="scheme"):
        guarded_fetch("ftp://example.com/file")


def test_url_with_no_hostname_rejected():
    with pytest.raises(BlockedUrlError, match="hostname"):
        guarded_fetch("http://")


def test_private_ip_rejected(monkeypatch):
    def fake_resolver(host):
        return "10.0.0.5"

    with pytest.raises(BlockedUrlError, match="disallowed"):
        guarded_fetch("http://internal.example.com/", resolver=fake_resolver)


def test_loopback_ip_rejected(monkeypatch):
    def fake_resolver(host):
        return "127.0.0.1"

    with pytest.raises(BlockedUrlError, match="disallowed"):
        guarded_fetch("http://localhost/", resolver=fake_resolver)


def test_link_local_ip_rejected(monkeypatch):
    def fake_resolver(host):
        return "169.254.1.1"

    with pytest.raises(BlockedUrlError, match="disallowed"):
        guarded_fetch("http://link-local.example.com/", resolver=fake_resolver)


def test_cloud_metadata_ip_rejected(monkeypatch):
    def fake_resolver(host):
        return "169.254.169.254"

    with pytest.raises(BlockedUrlError, match="disallowed"):
        guarded_fetch("http://metadata.example.com/", resolver=fake_resolver)


def test_public_ip_allowed(monkeypatch):
    def fake_resolver(host):
        return "93.184.216.34"  # public (example.com's old IP range)

    def fake_do_fetch(url, timeout_seconds, max_bytes):
        return b"hello world"

    monkeypatch.setattr("app.security.fetch._do_fetch", fake_do_fetch)

    result = guarded_fetch("http://public.example.com/", resolver=fake_resolver)
    assert result == b"hello world"


def test_resolver_failure_rejected():
    def failing_resolver(host):
        raise BlockedUrlError(f"could not resolve host: {host}")

    with pytest.raises(BlockedUrlError, match="could not resolve"):
        guarded_fetch("http://does-not-resolve.invalid/", resolver=failing_resolver)


def test_response_over_max_bytes_rejected(monkeypatch):
    def fake_resolver(host):
        return "93.184.216.34"

    def fake_do_fetch(url, timeout_seconds, max_bytes):
        raise BlockedUrlError(f"response exceeded max size of {max_bytes} bytes")

    monkeypatch.setattr("app.security.fetch._do_fetch", fake_do_fetch)

    with pytest.raises(BlockedUrlError, match="exceeded max size"):
        guarded_fetch("http://public.example.com/", resolver=fake_resolver, max_bytes=10)


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("10.0.0.1", True),
        ("172.16.0.1", True),
        ("192.168.1.1", True),
        ("127.0.0.1", True),
        ("169.254.1.1", True),
        ("169.254.169.254", True),
        ("0.0.0.0", True),
        ("8.8.8.8", False),
        ("93.184.216.34", False),
        ("1.1.1.1", False),
    ],
)
def test_is_blocked_ip(ip, expected):
    assert _is_blocked_ip(ip) is expected
