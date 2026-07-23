"""SSRF-safe HTTP helper for outbound fetches.

Centralizes the network egress used by web providers and the image
downloader. Every request:

- Validates the URL scheme (http/https only).
- Resolves the hostname and refuses any address that is private,
  loopback, link-local, multicast, reserved, or unspecified — so an
  attacker page cannot trick a fetcher into reaching `169.254.169.254`
  (cloud metadata), `127.0.0.1`, RFC1918, or `file://`.
- Follows redirects MANUALLY, re-validating each hop against the same
  gate.
- Streams the response into a fixed-size buffer so a hostile server
  cannot exhaust memory with an infinite or zip-bombed body.

The address check is BEST-EFFORT against DNS rebinding: the gate
resolves the hostname to validate it, but httpx re-resolves at connect
time, so a low-TTL record that flips between the two lookups can still
reach a private address. Closing that window needs the validated IP
pinned into the actual connection, which httpx does not support without
a custom transport; the residual risk is accepted and documented here.

Returns a small :class:`SafeResponse` dataclass instead of an
``httpx.Response`` so callers don't depend on httpx internals.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

_ALLOWED_SCHEMES = frozenset({"http", "https"})

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_USER_AGENT = "hyperresearch/0.1"

# Caller-intent size caps. Pick the smallest that fits the body type;
# the gate refuses anything larger. These are the DEFAULTS — callers with
# a FetchSettings in scope should pass its max_html_bytes / max_pdf_bytes
# / max_image_bytes fields instead, which are user-configurable and
# mirror these values.
MAX_BYTES_HTML = 10 * 1024 * 1024
MAX_BYTES_PDF = 25 * 1024 * 1024
MAX_BYTES_IMAGE = 2 * 1024 * 1024


class SafeHTTPError(Exception):
    """The SSRF gate refused this request, or the response exceeded a limit."""


@dataclass
class SafeResponse:
    """Minimal response wrapper. Avoids leaking httpx types to callers."""

    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes = field(repr=False)

    @property
    def text(self) -> str:
        charset = "utf-8"
        ct = self.headers.get("content-type", "")
        if "charset=" in ct.lower():
            charset = ct.lower().split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SafeHTTPError(f"DNS lookup failed for {host!r}: {exc}") from exc
    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            addrs.append(ipaddress.ip_address(info[4][0]))
        except (ValueError, IndexError):
            continue
    return addrs


def check_url(url: str) -> None:
    """Validate the URL is safe to fetch. Raises :class:`SafeHTTPError`.

    Best-effort: validation resolves the hostname here, but the connection
    made afterwards re-resolves it (see the module docstring on DNS
    rebinding).
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise SafeHTTPError(
            f"refusing URL with scheme {parsed.scheme!r}; only http/https are allowed"
        )
    if not parsed.hostname:
        raise SafeHTTPError(f"refusing URL with no hostname: {url!r}")
    addrs = _resolve(parsed.hostname)
    if not addrs:
        raise SafeHTTPError(f"refusing URL {url!r}: hostname did not resolve")
    for addr in addrs:
        if _is_blocked_ip(addr):
            raise SafeHTTPError(
                f"refusing URL {url!r}: hostname {parsed.hostname} resolves to "
                f"non-public address {addr}"
            )


def safe_get(
    url: str,
    *,
    max_bytes: int,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    headers: dict[str, str] | None = None,
    verify: bool | str = True,
    transport: httpx.BaseTransport | None = None,
) -> SafeResponse:
    """GET ``url`` with SSRF + size protection.

    ``max_bytes`` is required so callers consciously pick a cap. Pass the
    matching ``FetchSettings`` field when one is in scope, or a
    ``MAX_BYTES_*`` constant otherwise.

    ``transport`` is a test seam: it lets the suite exercise the redirect
    revalidation and size-cap logic against ``httpx.MockTransport``
    without opening sockets. Production callers must leave it None.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be > 0")

    request_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)

    current_url = url
    with httpx.Client(
        follow_redirects=False, timeout=timeout, verify=verify, transport=transport
    ) as client:
        for _ in range(max_redirects + 1):
            check_url(current_url)
            declared = None
            with client.stream("GET", current_url, headers=request_headers) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return _materialize(resp, b"", current_url)
                    current_url = str(httpx.URL(current_url).join(location))
                    continue

                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise SafeHTTPError(
                        f"refusing response from {current_url!r}: "
                        f"Content-Length {declared} exceeds cap {max_bytes}"
                    )

                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise SafeHTTPError(
                            f"refusing response from {current_url!r}: "
                            f"body exceeds cap {max_bytes} bytes"
                        )
                return _materialize(resp, bytes(body), current_url)

    raise SafeHTTPError(f"too many redirects (>{max_redirects}) starting at {url!r}")


def _materialize(resp: httpx.Response, body: bytes, final_url: str) -> SafeResponse:
    return SafeResponse(
        url=final_url,
        status_code=resp.status_code,
        headers={k.lower(): v for k, v in resp.headers.items()},
        content=body,
    )
