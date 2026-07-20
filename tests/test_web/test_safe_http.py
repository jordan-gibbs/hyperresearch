"""Tests for the SSRF gate in hyperresearch.web.safe_http."""

from __future__ import annotations

import socket
from unittest.mock import patch

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
