"""PDF fetch diagnostics.

Every `fetch_pdf` failure used to return a bare `None`, indistinguishable from
"this URL is not a PDF". When pymupdf was missing or broken — e.g. no wheel for
the platform — every PDF on every domain silently fell through to the browser
lane, arrived as binary, and was discarded as junk, with nothing logged to say
why. These tests pin the diagnostics, not just the happy path.

Offline: the download layer (`safe_get_pdf` / `safe_get`) is stubbed, no
network is touched. The lane lives in `hyperresearch.web.pdf` and is shared
by every provider; the crawl4ai module re-exports it under the old names.
"""

from __future__ import annotations

import builtins
import logging

import pytest

import hyperresearch.web.pdf as provider


class _Resp:
    def __init__(self, content: bytes, status: int = 200, content_type: str = "application/pdf"):
        self.content = content
        self.status_code = status
        self.headers = {"content-type": content_type}


@pytest.fixture
def stub_httpx(monkeypatch):
    """Replace the SSRF-gated download call with a canned response."""

    def _install(resp: _Resp):
        monkeypatch.setattr(provider, "safe_get_pdf", lambda url, settings: resp)

    return _install


@pytest.fixture(autouse=True)
def _reset_warning_latch():
    provider._PYMUPDF_MISSING_LOGGED = False
    yield
    provider._PYMUPDF_MISSING_LOGGED = False


def test_missing_pymupdf_logs_the_consequence(monkeypatch, caplog):
    """A missing pymupdf must not fail silently — it disables all PDF ingestion."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("no wheel for this platform")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with caplog.at_level(logging.ERROR, logger="hyperresearch.pdf"):
        assert provider.import_pymupdf() is None

    assert "pymupdf could not be imported" in caplog.text
    assert "discarded as junk" in caplog.text, "the log must name the actual consequence"


def test_missing_pymupdf_warning_is_not_repeated(monkeypatch, caplog):
    """One clear error, not one per fetched URL."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with caplog.at_level(logging.ERROR, logger="hyperresearch.pdf"):
        for _ in range(5):
            provider.import_pymupdf()

    assert caplog.text.count("pymupdf could not be imported") == 1


def test_non_pdf_response_logs_content_type_and_first_bytes(stub_httpx, caplog):
    """When the server returns HTML, say so — don't just return None."""
    stub_httpx(_Resp(b"<!doctype html><html>...", content_type="text/html"))

    with caplog.at_level(logging.WARNING, logger="hyperresearch.pdf"):
        assert provider.fetch_pdf("https://example.com/paper") is None

    assert "did not return PDF data" in caplog.text
    assert "text/html" in caplog.text


def test_http_error_status_is_logged(stub_httpx, caplog):
    """A 403 must be visible, not silently indistinguishable from 'not a PDF'."""
    stub_httpx(_Resp(b"", status=403, content_type="text/html"))

    with caplog.at_level(logging.WARNING, logger="hyperresearch.pdf"):
        assert provider.fetch_pdf("https://example.com/x.pdf") is None

    assert "403" in caplog.text


def test_magic_bytes_beat_a_wrong_content_type(stub_httpx):
    """A real PDF mislabelled as octet-stream must still be accepted.

    Servers routinely mislabel PDFs, and many PDF URLs carry no .pdf suffix.
    Trusting the header or the URL shape alone drops real PDFs on the floor.
    """
    pytest.importorskip("pymupdf")
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    # Needs to clear the >=300-char "near-empty content" rule to reach the
    # binary/junk checks this test is actually about.
    page.insert_text((36, 60), "Extractable text layer for the regression test.")
    for i in range(20):
        page.insert_text((36, 80 + i * 14), f"Line {i}: representative body text for extraction. " * 2)
    pdf_bytes = doc.tobytes()
    doc.close()

    stub_httpx(_Resp(pdf_bytes, content_type="application/octet-stream"))

    result = provider.fetch_pdf("https://example.com/download?id=123")
    assert result is not None, "mislabelled PDF was rejected"
    assert "Extractable text layer" in result.content
    assert result.looks_like_junk() is None


def test_html_masquerading_as_pdf_content_type_is_rejected(stub_httpx, caplog):
    """The inverse: a text/html body labelled application/pdf is not a PDF."""
    stub_httpx(_Resp(b"<html><body>Access denied</body></html>"))

    with caplog.at_level(logging.WARNING, logger="hyperresearch.pdf"):
        assert provider.fetch_pdf("https://example.com/x.pdf") is None

    assert "did not return PDF data" in caplog.text


def test_scanned_pdf_without_text_layer_explains_itself(stub_httpx, caplog):
    """An image-only PDF needs OCR — say that rather than returning a bare None."""
    pytest.importorskip("pymupdf")
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()  # blank page, no text layer
    pdf_bytes = doc.tobytes()
    doc.close()

    stub_httpx(_Resp(pdf_bytes))

    with caplog.at_level(logging.WARNING, logger="hyperresearch.pdf"):
        assert provider.fetch_pdf("https://example.com/scan.pdf") is None

    assert "no extractable text layer" in caplog.text
    assert "OCR" in caplog.text


def _cert_error() -> Exception:
    import ssl

    import httpx

    err = httpx.ConnectError("TLS handshake failed")
    err.__cause__ = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
    return err


def test_cert_error_refuses_with_no_unverified_retry(monkeypatch):
    """A certificate error is a refusal, never an automatic unverified retry —
    a MITM can serve a bad cert precisely to force such a retry. The refusal
    names the pdf_verify_tls opt-out so a trusted cert-broken mirror stays
    reachable by explicit operator decision."""
    from hyperresearch.web.safe_http import SafeHTTPError

    calls: list[bool] = []

    def fake_safe_get(url, *, max_bytes, timeout=None, headers=None, verify=True,
                      allow_private_hosts=()):
        calls.append(verify)
        raise _cert_error()

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)

    with pytest.raises(SafeHTTPError, match="pdf_verify_tls"):
        provider.safe_get_pdf(
            "https://broken-cert.example.edu/paper.pdf", provider.FetchSettings()
        )

    assert calls == [True], "exactly one verified attempt, no unverified retry"


def test_non_cert_error_propagates_untranslated(monkeypatch):
    """A refused connection is not a certificate problem — it must propagate
    as-is, without the pdf_verify_tls hint."""
    import httpx

    calls: list[bool] = []

    def fake_safe_get(url, *, max_bytes, timeout=None, headers=None, verify=True,
                      allow_private_hosts=()):
        calls.append(verify)
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)

    with pytest.raises(httpx.ConnectError):
        provider.safe_get_pdf("https://down.example.com/x.pdf", provider.FetchSettings())

    assert calls == [True]


def test_pdf_verify_tls_false_fetches_unverified(monkeypatch):
    """An explicit `pdf_verify_tls = false` in config is an operator decision:
    fetch unverified directly. SSRF/size gates still apply (same safe_get)."""
    calls: list[bool] = []

    def fake_safe_get(url, *, max_bytes, timeout=None, headers=None, verify=True,
                      allow_private_hosts=()):
        calls.append(verify)
        return _Resp(b"%PDF- direct")

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)

    resp = provider.safe_get_pdf(
        "https://mirror.example.org/x.pdf", provider.FetchSettings(pdf_verify_tls=False)
    )

    assert calls == [False], "config opt-out must fetch unverified on the first attempt"
    assert resp.content == b"%PDF- direct"


def test_failure_reason_is_kept_for_the_requested_url(stub_httpx):
    """The reason a PDF was declined is readable afterwards, keyed by the URL
    as the caller asked for it — not the rewritten arXiv pdf URL."""
    stub_httpx(_Resp(b"", status=403, content_type="text/html"))

    assert provider.fetch_pdf("https://arxiv.org/abs/2005.14165") is None
    assert provider.failure_reason("https://arxiv.org/abs/2005.14165") == "HTTP 403"


def test_failure_reason_is_cleared_on_success(stub_httpx):
    pytest.importorskip("pymupdf")
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    for i in range(20):
        page.insert_text((36, 60 + i * 14), f"Line {i}: body text for the regression test. " * 2)
    pdf_bytes = doc.tobytes()
    doc.close()

    stub_httpx(_Resp(b"", status=500))
    assert provider.fetch_pdf("https://example.com/x.pdf") is None
    assert provider.failure_reason("https://example.com/x.pdf") == "HTTP 500"

    stub_httpx(_Resp(pdf_bytes))
    assert provider.fetch_pdf("https://example.com/x.pdf") is not None
    assert provider.failure_reason("https://example.com/x.pdf") is None


def test_document_handle_is_closed_when_page_iteration_raises(stub_httpx, monkeypatch):
    """An encrypted or damaged PDF that raises mid-iteration must not leak
    the open document."""
    closed: list[bool] = []

    class _Doc:
        page_count = 3

        def __iter__(self):
            raise RuntimeError("cannot read page: document is encrypted")

        def close(self):
            closed.append(True)

    class _PyMuPDF:
        @staticmethod
        def open(stream, filetype):
            return _Doc()

    monkeypatch.setattr(provider, "import_pymupdf", lambda: _PyMuPDF())
    stub_httpx(_Resp(b"%PDF-1.7 " + b"x" * 4096))

    assert provider.fetch_pdf("https://example.com/locked.pdf") is None
    assert closed == [True]
    assert "encrypted" in (provider.failure_reason("https://example.com/locked.pdf") or "")


def test_crawl4ai_module_keeps_the_old_names():
    """Callers and tests patched `crawl4ai_provider._fetch_pdf` for a long time;
    the aliases stay so the move is not a silent break."""
    crawl4ai_provider = pytest.importorskip("hyperresearch.web.crawl4ai_provider")

    assert crawl4ai_provider._fetch_pdf is provider.fetch_pdf
    assert crawl4ai_provider._is_pdf_url is provider.is_pdf_url
    assert crawl4ai_provider._safe_get_pdf is provider.safe_get_pdf
