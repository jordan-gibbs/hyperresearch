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
    """`ipaddress.ip_address` rejects these encodings. The numeric ones are
    refused before any lookup (a browser parses them as IPv4 in its own
    grammar); the rest fall to the resolver, which normalizes them to
    127.0.0.1. getaddrinfo is stubbed so the test is deterministic and
    offline. Either way they are never parsed as public."""
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))]
        with pytest.raises(SafeHTTPError, match=r"non-public address|numeric host"):
            check_url(url)


# ---------------------------------------------------------------------------
# check_url — RFC 3986 (urlparse, httpx) vs WHATWG (Chromium) disagreements.
# The crawl4ai lane hands the URL to Chromium, so a spelling the parsers
# disagree on lets the gate approve one host while the browser connects to
# another. getaddrinfo is stubbed to a public address: if the gate fell
# through to resolution, these would be allowed.
# ---------------------------------------------------------------------------


@pytest.fixture
def public_dns():
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))]
        yield gai


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1\\@evil.com/",  # urlparse/httpx: evil.com; Chromium: 127.0.0.1
        "HTTPS://127.0.0.1\\@evil.com/",
        "http://127.0.0.1:80\\@evil.com/",
        "http://user@127.0.0.1\\@evil.com/",
        "http://169.254.169.254\\@evil.com/latest/meta-data/",
        "http://127.0.0.1\\@evil.com",  # no path at all
        " http://127.0.0.1\\@evil.com/",  # after the leading-whitespace strip
    ],
)
def test_check_url_refuses_backslash_in_authority(url, public_dns):
    with pytest.raises(SafeHTTPError, match="backslash in the authority"):
        check_url(url)


def test_check_url_backslash_then_private_userinfo_host_still_refused():
    """The mirror image: the RFC parsers see 127.0.0.1, Chromium sees
    evil.com. Fetching it would be harmless in the browser, but the gate
    must not let it through on any lane."""
    with pytest.raises(SafeHTTPError):
        check_url("http://evil.com\\@127.0.0.1/")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/path\\with\\backslash",
        "https://example.com/a?q=C:\\dir\\file",
        "https://example.com/#frag\\x",
        "https://example.com?\\@127.0.0.1",
    ],
)
def test_check_url_allows_backslash_after_the_authority(url, public_dns):
    """Past the first '/', '?' or '#', every parser is in the path, query or
    fragment. Chromium turns a path backslash into '/', which changes the
    path but cannot move the host, so these stay fetchable."""
    check_url(url)


@pytest.mark.parametrize(
    "url",
    ["http:\\\\127.0.0.1/", "http:/\\127.0.0.1/", "http:/127.0.0.1/", "http:127.0.0.1/"],
)
def test_check_url_refuses_whatwg_only_authority_forms(url):
    """WHATWG finds a host in all of these (it skips any mix of slashes and
    backslashes after a special scheme); the RFC parsers find none."""
    with pytest.raises(SafeHTTPError, match="no hostname"):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1\t@evil.com/",  # WHATWG strips tab/newline anywhere
        "http://127.0.0.1\n@evil.com/",
        "http://127.0.0.1\r\\@evil.com/",
        "http://127.0.0.1\x00@evil.com/",
    ],
)
def test_check_url_refuses_control_characters_inside_the_url(url, public_dns):
    with pytest.raises(SafeHTTPError, match="unparseable"):
        check_url(url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.%31/", "http://%31%32%37.0.0.1/", "http://%6cocalhost/"]
)
def test_check_url_refuses_percent_encoded_host(url, public_dns):
    """Chromium percent-decodes the host; httpx and getaddrinfo do not."""
    with pytest.raises(SafeHTTPError, match="percent-encoded hostname"):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.1/",
        "http://0x7f.1/",
        "http://0177.0.0.1/",
        "http://127.0.0.1./",
        "http://example.0x10/",
        "http://1.2.3.4.5/",
    ],
)
def test_check_url_refuses_non_canonical_numeric_host(url, public_dns):
    """WHATWG reads a host whose last label is numeric as IPv4 in its own
    grammar; getaddrinfo's reading varies by platform and may fall to DNS.
    httpx itself rejects some of these ("Invalid IPv4")."""
    with pytest.raises(SafeHTTPError, match=r"numeric host|Invalid IPv4"):
        check_url(url)


@pytest.mark.parametrize(
    "url", ["http://8.8.8.8/", "http://example.com/", "http://a1.example.com/", "http://x.com123/"]
)
def test_check_url_numeric_rule_spares_ordinary_hosts(url, public_dns):
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


# ---------------------------------------------------------------------------
# CGNAT (RFC 6598) — 100.64.0.0/10 is not covered by any ipaddress is_*
# property, so only the explicit network check refuses it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://100.64.0.1/", "http://100.127.255.254/"])
def test_check_url_rejects_cgnat_range(url):
    """Shared address space is never a public destination, yet it passes
    every ipaddress ``is_*`` property (checked through 3.11.9)."""
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url(url)


@pytest.mark.parametrize("url", ["http://100.63.255.255/", "http://100.128.0.1/"])
def test_check_url_allows_cgnat_neighbors(url):
    """The block is exactly /10 — addresses either side stay fetchable."""
    check_url(url)


# ---------------------------------------------------------------------------
# 6to4 (RFC 3056) — 2002:AABB:CCDD::/48 embeds the IPv4 address A.B.C.D, so
# the check must decode it; ipaddress does not flag the prefix on its own
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://[2002:7f00:1::]/",        # 127.0.0.1
        "http://[2002:c0a8:101::]/",      # 192.168.1.1
        "http://[2002:a9fe:a9fe::]/",     # 169.254.169.254, cloud metadata
        "http://[2002:6440:1::]/",        # 100.64.0.1, CGNAT
    ],
)
def test_check_url_rejects_6to4_wrapping_private_ipv4(url):
    """A deprecated transport, but the embedded address is what would be
    reached, and a literal in the URL skips DNS entirely."""
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url(url)


def test_check_url_allows_6to4_wrapping_public_ipv4():
    """2002:0808:0808:: embeds 8.8.8.8 and stays fetchable — the block is on
    the embedded address, not the prefix."""
    check_url("http://[2002:808:808::]/")


# ---------------------------------------------------------------------------
# IPv4-mapped IPv6 (::ffff:a.b.c.d) is classified by the embedded IPv4. The
# ipaddress properties disagree across interpreters: 3.11 and 3.13 report a
# mapped CGNAT address as public, 3.12 reports even a mapped public address
# as reserved.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://[::ffff:10.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",  # mapped cloud metadata
        "http://[::ffff:100.64.0.1]/",  # mapped CGNAT: allowed on 3.11 and 3.13
    ],
)
def test_check_url_rejects_ipv4_mapped_private_forms(url):
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url(url)


def test_check_url_allows_ipv4_mapped_public():
    """A mapped PUBLIC address stays fetchable: the verdict follows the
    embedded address, where 3.12's is_reserved refused it wholesale."""
    check_url("http://[::ffff:8.8.8.8]/")


# ---------------------------------------------------------------------------
# allow_private_hosts — the [fetch] escape hatch for intranet mirrors
# ---------------------------------------------------------------------------


def test_allowlist_cidr_admits_private_address():
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("10.0.0.5", 0))]
        check_url("http://mirror.example/x", allow_private_hosts=("10.0.0.0/8",))


def test_allowlist_cidr_is_not_a_blanket_waiver():
    """Allowlisting one private network must not admit OTHER private space."""
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("192.168.1.5", 0))]
        with pytest.raises(SafeHTTPError, match="non-public address"):
            check_url("http://mirror.example/x", allow_private_hosts=("10.0.0.0/8",))


def test_allowlist_bare_ip_entry_admits_exactly_one_host():
    check_url("http://192.168.1.20/wiki", allow_private_hosts=("192.168.1.20",))
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url("http://192.168.1.21/wiki", allow_private_hosts=("192.168.1.20",))


def test_allowlist_hostname_admits_by_name_case_insensitively():
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("10.0.0.5", 0))]
        check_url("http://Papers.INTERNAL/x", allow_private_hosts=("papers.internal",))


def test_allowlist_hostname_is_exact_not_a_suffix_match():
    """``papers.internal`` must not admit ``evil-papers.internal``."""
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("10.0.0.5", 0))]
        with pytest.raises(SafeHTTPError, match="non-public address"):
            check_url(
                "http://evil-papers.internal/x",
                allow_private_hosts=("papers.internal",),
            )


def test_allowlist_does_not_bypass_the_scheme_gate():
    with pytest.raises(SafeHTTPError, match="scheme"):
        check_url("ftp://papers.internal/x", allow_private_hosts=("papers.internal",))


def test_allowlist_malformed_cidr_is_a_loud_error():
    """A typo'd CIDR must not silently degrade into "entry ignored" — that
    failure mode looks exactly like an SSRF refusal of the mirror it was
    supposed to admit."""
    with pytest.raises(SafeHTTPError, match="invalid allow_private_hosts"):
        check_url("http://8.8.8.8/", allow_private_hosts=("10.0.0.0/33",))


def test_safe_get_redirect_to_allowlisted_private_host_is_followed():
    """The allowlist is threaded into per-hop revalidation: a public host
    redirecting onto an allowlisted mirror is followed, not refused."""
    transport = _transport({
        "/start": httpx.Response(302, headers={"location": "http://192.168.1.20/paper"}),
        "/paper": httpx.Response(200, content=b"mirror content"),
    })
    resp = safe_get(
        "http://8.8.8.8/start", max_bytes=1024, transport=transport,
        allow_private_hosts=("192.168.1.20",),
    )
    assert resp.content == b"mirror content"


# ---------------------------------------------------------------------------
# Hostname spellings: allowlist matching follows DNS equivalence, not string
# equality. The resolver is stubbed to answer with a private address, so a
# spelling that misses its entry is refused rather than looked up for real.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "entry"),
    [
        # A trailing dot marks an absolute name: same host when looked up as one.
        ("http://mirror.internal./x", "mirror.internal"),
        ("http://mirror.internal/x", "mirror.internal."),
        ("http://Mirror.INTERNAL./x", "mirror.internal"),
        # IDN hosts arrive as unicode or punycode depending on who typed them.
        ("http://münchen.example/x", "xn--mnchen-3ya.example"),
        ("http://xn--mnchen-3ya.example/x", "münchen.example"),
    ],
)
def test_allowlist_hostname_matches_dns_equivalent_spelling(url, entry):
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("10.0.0.5", 0))]
        check_url(url, allow_private_hosts=(entry,))


@pytest.mark.parametrize(
    ("url", "entry"),
    [
        ("http://strasse.example/x", "straße.example"),
        ("http://straße.example/x", "strasse.example"),
    ],
)
def test_allowlist_hostname_does_not_match_idna2003_mapping(url, entry):
    """IDNA 2003 (the stdlib "idna" codec) maps "straße" to "strasse", but
    httpx sends "xn--strae-oqa": two separately registrable names. An entry
    for one must not admit the other."""
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("10.0.0.5", 0))]
        with pytest.raises(SafeHTTPError, match="non-public address"):
            check_url(url, allow_private_hosts=(entry,))


def test_allowlist_entry_with_ideographic_full_stop_names_the_dotted_host():
    """IDNA and httpx separate labels on U+3002, so this entry names
    "mirror.internal", not the single label its punycode would spell."""
    entry = "mirror\u3002internal"
    one_label = "xn--" + entry.encode("punycode").decode("ascii")
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("10.0.0.5", 0))]
        check_url("http://mirror.internal/x", allow_private_hosts=(entry,))
        with pytest.raises(SafeHTTPError, match="non-public address"):
            check_url(f"http://{one_label}/x", allow_private_hosts=(entry,))


@pytest.mark.parametrize("entry", ["fe80::1%eth0", "[fe80::1%eth0]"])
def test_allowlist_scoped_ipv6_entry_parses_as_its_address(entry):
    """A scoped entry is an address, not a hostname, and matches by address
    bits whatever the scope."""
    import ipaddress

    from hyperresearch.web.safe_http import _parse_allowlist

    hostnames, networks = _parse_allowlist((entry,))
    assert hostnames == frozenset()
    assert len(networks) == 1
    assert ipaddress.ip_address("fe80::1") in networks[0]


def test_allowlist_scoped_ipv6_url_allowed_by_bracketed_scoped_entry():
    check_url("http://[fe80::1%eth0]/x", allow_private_hosts=("[fe80::1%eth0]",))


def test_scoped_ipv6_url_refused_without_entry():
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url("http://[fe80::1%eth0]/x")


def test_allowlist_percent_in_non_address_entry_is_a_loud_error():
    with pytest.raises(SafeHTTPError, match="scope id"):
        check_url("http://8.8.8.8/", allow_private_hosts=("my%host",))


@pytest.mark.parametrize(
    "entry",
    [
        "\uff45xample.com",  # fullwidth "e"
        "mu\u0308nchen.example",  # NFD: "u" plus a combining diaeresis
        "ex\u00adample.com",  # soft hyphen
        "\u200b.example",  # zero-width space
    ],
)
def test_allowlist_entry_httpx_would_refuse_is_a_loud_error(entry):
    """httpx refuses each of these hosts in a URL (IDNA 2008 rejects them), so
    the entry could never match and must not be accepted silently."""
    with pytest.raises(SafeHTTPError, match="not a valid IDNA hostname"):
        check_url("http://8.8.8.8/", allow_private_hosts=(entry,))


# ---------------------------------------------------------------------------
# The gate looks up the name the connection will. httpx sends an IDN host in
# its IDNA 2008 form, while getaddrinfo encodes a unicode name with the stdlib
# IDNA 2003 codec, which maps the deviation characters (ß, ς, ZWJ, ZWNJ) to a
# different name. A zone owner could point the two at different addresses.
# ---------------------------------------------------------------------------


_WIRE_FORMS = [
    ("http://straße.example/x", "xn--strae-oqa.example"),  # IDNA 2003: strasse
    # Final sigma; IDNA 2003 folds it to the medial sigma, "xn--4xa".
    ("http://ς.example/x", "xn--3xa.example"),
    # Devanagari ka, virama, ZERO WIDTH JOINER, ssa; IDNA 2003 drops the ZWJ
    ("http://\u0915\u094d\u200d\u0937.example/x", "xn--11b2ezcw70k.example"),
]


@pytest.mark.parametrize(("url", "wire_host"), _WIRE_FORMS)
def test_check_url_resolves_the_name_httpx_connects_to(url, wire_host):
    assert httpx.URL(url).raw_host.decode("ascii") == wire_host
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("8.8.8.8", 0))]
        check_url(url)
    assert [c.args[0] for c in gai.call_args_list] == [wire_host]


def test_safe_get_resolves_the_name_each_hop_requests():
    """Every hop, the entry URL included, is checked on the host its request
    is sent to."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.raw_host.decode("ascii"))
        if request.url.path == "/start":
            location = "http://ς.example/paper".encode()
            return httpx.Response(302, headers=[(b"location", location)])
        return httpx.Response(200, content=b"ok")

    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.return_value = [(socket.AF_INET, None, None, "", ("8.8.8.8", 0))]
        resp = safe_get(
            "http://straße.example/start", max_bytes=1024,
            transport=httpx.MockTransport(handler),
        )
    assert resp.content == b"ok"
    assert requested == ["xn--strae-oqa.example", "xn--3xa.example"]
    assert [c.args[0] for c in gai.call_args_list] == requested


# ---------------------------------------------------------------------------
# Exception containment: check_url raises SafeHTTPError and nothing else, so
# the batch fetch path's per-URL handler can skip a bad URL
# ---------------------------------------------------------------------------


def test_check_url_malformed_ipv6_brackets_raise_safe_error():
    """urlparse() itself raises ValueError("Invalid IPv6 URL") here."""
    with pytest.raises(SafeHTTPError, match="unparseable"):
        check_url("http://[::1/x")


def test_check_url_overlong_label_raises_safe_error():
    """getaddrinfo raises UnicodeError, not gaierror, when IDNA encoding
    rejects a 300-character label. No lookup is sent."""
    with pytest.raises(SafeHTTPError, match="DNS lookup failed"):
        check_url("http://" + "a" * 300 + ".com/x")


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/pa\udcffper.pdf",
        "http://8.8.8.8/x?q=\udcff",
        "http://8.8.8.8/x#\ud800",
    ],
)
def test_check_url_unencodable_url_raises_safe_error(url):
    """A lone surrogate (what a non-UTF-8 byte in a command-line argument
    becomes) makes httpx.URL raise UnicodeEncodeError."""
    with pytest.raises(SafeHTTPError, match="unparseable"):
        check_url(url)


# ---------------------------------------------------------------------------
# allow_private_hosts entry hygiene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", ["192.168.1.20:8443", "mirror.internal:8443"])
def test_allowlist_entry_with_port_is_a_loud_error(entry):
    """A host:port entry would otherwise become a hostname that can never
    match (URL hostnames carry no port): a silent dead entry presenting as
    an SSRF refusal of the user's own mirror."""
    with pytest.raises(SafeHTTPError, match="drop the port"):
        check_url("http://8.8.8.8/", allow_private_hosts=(entry,))


def test_allowlist_bracketed_ipv6_entry_admits_the_literal():
    """A bracketed IPv6 entry (URL notation) parses as the address itself
    instead of becoming a hostname that never matches."""
    check_url("http://[::1]/", allow_private_hosts=("[::1]",))


@pytest.mark.parametrize("url", [" http://8.8.8.8/", "\t http://8.8.8.8/", "\x00http://8.8.8.8/"])
def test_check_url_strips_leading_whitespace_as_urlparse_does(url):
    """urlparse drops leading C0 controls and spaces; httpx alone reads the
    URL as relative and finds no host. The gate checks the same host both
    see instead of looking up an empty name."""
    check_url(url)


@pytest.mark.parametrize("url", [" http://127.0.0.1/", "\x0bhttp://10.0.0.1/"])
def test_check_url_leading_whitespace_still_ip_gated(url):
    with pytest.raises(SafeHTTPError, match="non-public address"):
        check_url(url)
