"""The builtin provider refuses a bad TLS certificate as CertVerificationError.

The PDF lane (`web.pdf.safe_get_pdf`) and the crawl4ai provider already raise
`CertVerificationError` on a certificate failure. The builtin provider's HTML
lane did not: `safe_get` let the raw `httpx.ConnectError` escape, so the same
refusal surfaced as an opaque ssl string and callers could not tell it apart
from a refused connection or a DNS failure.

Two layers here. The unit tests fake the httpx error chain at `safe_get`. The
end-to-end tests run a real TLS server on loopback with a self-signed
certificate, which also checks the error-chain walk against the nesting httpx
produces today, and count completed handshakes: a client that verifies never
completes one, so a nonzero count means some lane retried without
verification.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import socket
import ssl
import threading

import httpx
import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.config import FetchSettings
from hyperresearch.web.builtin import BuiltinProvider
from hyperresearch.web.safe_http import CertVerificationError

runner = CliRunner()


def _cert_error() -> Exception:
    err = httpx.ConnectError("TLS handshake failed")
    err.__cause__ = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
    return err


def test_cert_failure_raises_cert_verification_error(monkeypatch):
    calls: list[bool | str] = []

    def fake_safe_get(url, *, max_bytes, timeout=None, headers=None, verify=True,
                      allow_private_hosts=()):
        calls.append(verify)
        raise _cert_error()

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)

    with pytest.raises(CertVerificationError, match="certificate verification failed"):
        BuiltinProvider().fetch("https://broken-cert.example.edu/page")

    assert calls == [True], "exactly one verified attempt, no unverified retry"


def test_non_cert_connect_error_propagates_untranslated(monkeypatch):
    def fake_safe_get(url, *, max_bytes, timeout=None, headers=None, verify=True,
                      allow_private_hosts=()):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)

    with pytest.raises(httpx.ConnectError, match="connection refused"):
        BuiltinProvider().fetch("https://down.example.com/page")


# ---------------------------------------------------------------------------
# End to end: a real self-signed TLS server on loopback
# ---------------------------------------------------------------------------


@pytest.fixture
def self_signed_server(tmp_path):
    """HTTPS server on 127.0.0.1 with a self-signed cert. Yields (base_url, stats)."""
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)

    stats = {"connections": 0, "handshakes_completed": 0}
    body = b"<html><title>served</title><body>" + b"page text " * 200 + b"</body></html>"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.05)  # so the accept loop notices `stop` promptly
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(5)
            stats["connections"] += 1
            try:
                with ctx.wrap_socket(conn, server_side=True) as tls:
                    stats["handshakes_completed"] += 1
                    tls.recv(4096)
                    tls.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                        b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body)
                        + body
                    )
            except (OSError, ssl.SSLError):
                conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{listener.getsockname()[1]}", stats
    finally:
        stop.set()
        thread.join(timeout=5)
        listener.close()


def test_real_self_signed_cert_raises_cert_verification_error(self_signed_server):
    base, stats = self_signed_server
    prov = BuiltinProvider(FetchSettings(allow_private_hosts=("127.0.0.1",)))

    with pytest.raises(CertVerificationError, match="certificate verification failed"):
        prov.fetch(f"{base}/page")

    assert stats["connections"] == 1
    assert stats["handshakes_completed"] == 0


@pytest.fixture
def cert_vault(tmp_path, monkeypatch, self_signed_server):
    """A builtin-provider vault that may reach loopback, with the open-access
    rescue armed to hand back the refused host itself: the worst case for a
    lane that might retry a cert-refused source."""
    base, stats = self_signed_server
    root = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(root), "--name", "Cert Test"]).exit_code == 0
    cfg = root / ".hyperresearch" / "config.toml"
    text = cfg.read_text(encoding="utf-8")
    assert text.count("allow_private_hosts = []") == 1
    cfg.write_text(
        text.replace("allow_private_hosts = []", 'allow_private_hosts = ["127.0.0.1"]'),
        encoding="utf-8",
    )

    from hyperresearch.core import oa, scholar

    rescues: list[str] = []

    def candidates(conn, doi, ttl_days, email=None, prefer_published=False):
        rescues.append(doi)
        yield oa.OALocation(url=f"{base}/open-copy", resolver="unpaywall", kind="page")

    # A doi.org link whose publisher fails TLS carries its DOI in the URL; a
    # loopback URL cannot, so supply the DOI directly.
    monkeypatch.setattr(scholar, "extract_doi", lambda url, raw_html=None, content=None: "10.1234/x")
    monkeypatch.setattr(oa, "iter_oa_candidates", candidates)
    monkeypatch.setattr(oa, "check_oa_url", lambda url: (True, ""))
    monkeypatch.chdir(root)
    return base, stats, rescues


def test_cli_single_fetch_reports_the_cert_refusal(cert_vault):
    base, stats, rescues = cert_vault

    result = runner.invoke(app, ["fetch", f"{base}/paper", "--provider", "builtin", "-j"])

    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["ok"] is False
    assert "certificate verification failed" in payload["error"]
    assert rescues == ["10.1234/x"]
    # Two connections: the fetch, then the rescue's attempt at the same host.
    # Neither completed a handshake, so neither lane skipped verification.
    assert stats["connections"] == 2
    assert stats["handshakes_completed"] == 0


def test_cli_batch_fetch_reports_the_cert_refusal(cert_vault):
    base, stats, rescues = cert_vault

    result = runner.invoke(app, ["fetch-batch", f"{base}/paper", "--provider", "builtin", "-j"])

    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    failed = payload["data"]["failed_urls"]
    assert [f["url"] for f in failed] == [f"{base}/paper"]
    assert "certificate verification failed" in failed[0]["error"]
    assert rescues == ["10.1234/x"]
    # Two connections: the fetch, then the rescue's attempt at the same host.
    # Neither completed a handshake, so neither lane skipped verification.
    assert stats["connections"] == 2
    assert stats["handshakes_completed"] == 0
