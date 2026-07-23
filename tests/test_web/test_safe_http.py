"""Tests for the SSRF gate in hyperresearch.web.safe_http."""

from __future__ import annotations

import socket
from unittest.mock import patch

import httpx
import pytest

from hyperresearch.web.safe_http import (
    MAX_BYTES_HTML,
    SafeHTTPError,
    check_url,
    safe_get,
)

# ---------------------------------------------------------------------------
# check_url — scheme and address validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "ftp://example.com/x",
        "data:text/html,<script>alert(1)</script>",
        "javascript:alert(1)",
    ],
)
def test_check_url_rejects_non_http_schemes(url):
    with pytest.raises(SafeHTTPError, match="scheme"):
        check_url(url)


def test_check_url_rejects_no_hostname():
    with pytest.raises(SafeHTTPError, match="no hostname"):
        check_url("http:///path")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.1.2.3/",
        "http://10.0.0.1/",
        "http://10.255.255.255/",
        "http://172.16.0.1/",
        "http://172.31.255.254/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # AWS IMDS
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
    ],
)
def test_check_url_rejects_private_and_loopback_ips(url):
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/",
        "https://1.1.1.1/",
        "http://93.184.216.34/",  # example.com at time of writing; literal so no DNS
    ],
)
def test_check_url_allows_public_ip_literals(url):
    check_url(url)  # should not raise


def test_check_url_dns_resolved_private_rejected():
    """Hostnames that resolve to private addresses are refused — even when
    the literal looks public."""
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("10.0.0.5", 0))]
        with pytest.raises(SafeHTTPError, match="non-public address"):
            check_url("http://example.com/x")


def test_check_url_dns_resolved_mixed_any_private_rejected():
    """If even ONE of the resolved addresses is private, refuse."""
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [
            (socket.AF_INET, None, None, "", ("8.8.8.8", 0)),
            (socket.AF_INET, None, None, "", ("10.0.0.5", 0)),
        ]
        with pytest.raises(SafeHTTPError, match="non-public address"):
            check_url("http://example.com/x")


def test_check_url_dns_failure_raises():
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.side_effect = socket.gaierror("nope")
        with pytest.raises(SafeHTTPError, match="DNS lookup failed"):
            check_url("http://nonexistent.invalid/x")


# ---------------------------------------------------------------------------
# check_url — encoded-loopback bypass vectors. These are the forms an attacker
# reaches for once the plain "http://127.0.0.1/" literal is blocked. Grouped by
# whether they resolve purely from the string (parse-only) or need the resolver.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6 — blocked as is_private
        "http://[64:ff9b::7f00:1]/",  # NAT64 well-known prefix — blocked as is_reserved
        "http://8.8.8.8@127.0.0.1/",  # userinfo trick: hostname is 127.0.0.1, not 8.8.8.8
    ],
)
def test_check_url_rejects_parse_only_loopback_bypasses(url):
    """These encode loopback/reserved space without a DNS lookup — the IP
    literal or the real hostname is right there in the URL. If the address
    classifier stops covering mapped/NAT64/reserved ranges, or urlparse's
    hostname extraction is second-guessed, one of these silently reaches an
    internal address."""
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",  # decimal 127.0.0.1
        "http://0x7f000001/",  # hex 127.0.0.1
        "http://017700000001/",  # octal 127.0.0.1
        "http://localhost./",  # trailing-dot hostname
    ],
)
def test_check_url_rejects_resolver_dependent_loopback_bypasses(url):
    """`ipaddress.ip_address` rejects these numeric encodings, so they fall to
    the resolver, which normalizes them to 127.0.0.1. getaddrinfo is stubbed
    so the test is deterministic and offline. This pins the contract that such
    forms are *resolved and gated*, not parsed as public — a regression that
    made `_resolve` parse the literal itself (e.g. via inet_aton) would need to
    keep blocking them."""
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))]
        with pytest.raises(SafeHTTPError, match="non-public address"):
            check_url(url)


def test_check_url_uppercase_http_scheme_is_normalized_then_ip_gated():
    """An uppercase HTTP scheme must not fail open: it normalizes to http and
    the loopback host is still refused by the address gate, not waved through
    as an unrecognized scheme."""
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url("HTTP://127.0.0.1/")


def test_check_url_uppercase_disallowed_scheme_still_rejected():
    """Scheme matching is case-folded on the reject path too — FILE:// is
    refused exactly like file://, not accidentally allowed by case."""
    with pytest.raises(SafeHTTPError, match="scheme"):
        check_url("FILE:///etc/passwd")


# ---------------------------------------------------------------------------
# safe_get — refuses bad URLs without even attempting a connection
# ---------------------------------------------------------------------------


def test_safe_get_refuses_private_ip_without_network():
    """No network mocking needed — the SSRF gate must reject before any
    socket is opened."""
    with pytest.raises(SafeHTTPError):
        safe_get("http://127.0.0.1/x", max_bytes=MAX_BYTES_HTML)


def test_safe_get_refuses_file_scheme():
    with pytest.raises(SafeHTTPError, match="scheme"):
        safe_get("file:///etc/passwd", max_bytes=MAX_BYTES_HTML)


def test_safe_get_requires_positive_max_bytes():
    with pytest.raises(ValueError):
        safe_get("http://example.com/", max_bytes=0)


# ---------------------------------------------------------------------------
# Redirect revalidation and size caps — exercised offline via the transport
# seam (httpx.MockTransport), so no socket is ever opened. All URLs use
# public IP literals so check_url never needs DNS.
# ---------------------------------------------------------------------------


def _transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    """Map url-path -> canned response."""

    def handler(request: httpx.Request) -> httpx.Response:
        return routes[request.url.path]

    return httpx.MockTransport(handler)


def test_redirect_to_private_address_is_refused():
    """Every redirect hop goes back through the SSRF gate — a public host
    must not be able to bounce the fetcher into loopback/RFC1918."""
    transport = _transport({
        "/start": httpx.Response(302, headers={"location": "http://127.0.0.1/secret"}),
    })
    with pytest.raises(SafeHTTPError, match="non-public address"):
        safe_get("http://8.8.8.8/start", max_bytes=1024, transport=transport)


def test_relative_redirect_is_resolved_and_followed():
    transport = _transport({
        "/a": httpx.Response(301, headers={"location": "/b"}),
        "/b": httpx.Response(200, content=b"made it"),
    })
    resp = safe_get("http://8.8.8.8/a", max_bytes=1024, transport=transport)
    assert resp.status_code == 200
    assert resp.content == b"made it"
    assert resp.url == "http://8.8.8.8/b"


def test_too_many_redirects_refused():
    transport = _transport({
        "/loop": httpx.Response(302, headers={"location": "/loop"}),
    })
    with pytest.raises(SafeHTTPError, match="too many redirects"):
        safe_get("http://8.8.8.8/loop", max_bytes=1024, transport=transport)


def test_declared_content_length_over_cap_refused():
    """An honest Content-Length over the cap is refused up front, before the
    body is streamed. Response(content=...) auto-sets the header; the match
    on "Content-Length" proves the header check fired, not the stream cap."""
    transport = _transport({
        "/big": httpx.Response(200, content=b"x" * 2048),
    })
    with pytest.raises(SafeHTTPError, match="Content-Length"):
        safe_get("http://8.8.8.8/big", max_bytes=1024, transport=transport)


def test_streamed_body_over_cap_refused():
    """A body that exceeds the cap mid-stream (no Content-Length header, as
    with chunked encoding) is cut off — a lying or chunked server cannot
    exhaust memory. Uses a raw byte stream because Response(content=...)
    would set Content-Length and trip the earlier header check instead."""

    class _ChunkStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(4):
                yield b"x" * 512

    transport = _transport({
        "/liar": httpx.Response(200, stream=_ChunkStream()),
    })
    with pytest.raises(SafeHTTPError, match="body exceeds cap"):
        safe_get("http://8.8.8.8/liar", max_bytes=1024, transport=transport)


def test_body_at_cap_passes():
    transport = _transport({
        "/fits": httpx.Response(200, content=b"x" * 1024),
    })
    resp = safe_get("http://8.8.8.8/fits", max_bytes=1024, transport=transport)
    assert resp.content == b"x" * 1024
