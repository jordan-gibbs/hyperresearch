"""PDF fetch diagnostics.

Every `_fetch_pdf` failure used to return a bare `None`, indistinguishable from
"this URL is not a PDF". When pymupdf was missing or broken — e.g. no wheel for
the platform — every PDF on every domain silently fell through to the browser
lane, arrived as binary, and was discarded as junk, with nothing logged to say
why. These tests pin the diagnostics, not just the happy path.

Offline: httpx is stubbed, no network is touched.
"""

from __future__ import annotations

import builtins
import logging

import pytest

import hyperresearch.web.crawl4ai_provider as provider


class _Resp:
    def __init__(self, content: bytes, status: int = 200, content_type: str = "application/pdf"):
        self.content = content
        self.status_code = status
        self.headers = {"content-type": content_type}


@pytest.fixture
def stub_httpx(monkeypatch):
    """Replace httpx.get with a canned response."""

    def _install(resp: _Resp):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **k: resp)

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
        assert provider._import_pymupdf() is None

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
            provider._import_pymupdf()

    assert caplog.text.count("pymupdf could not be imported") == 1


def test_non_pdf_response_logs_content_type_and_first_bytes(stub_httpx, caplog):
    """When the server returns HTML, say so — don't just return None."""
    stub_httpx(_Resp(b"<!doctype html><html>...", content_type="text/html"))

    with caplog.at_level(logging.WARNING, logger="hyperresearch.pdf"):
        assert provider._fetch_pdf("https://example.com/paper") is None

    assert "did not return PDF data" in caplog.text
    assert "text/html" in caplog.text


def test_http_error_status_is_logged(stub_httpx, caplog):
    """A 403 must be visible, not silently indistinguishable from 'not a PDF'."""
    stub_httpx(_Resp(b"", status=403, content_type="text/html"))

    with caplog.at_level(logging.WARNING, logger="hyperresearch.pdf"):
        assert provider._fetch_pdf("https://example.com/x.pdf") is None

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

    result = provider._fetch_pdf("https://example.com/download?id=123")
    assert result is not None, "mislabelled PDF was rejected"
    assert "Extractable text layer" in result.content
    assert result.looks_like_junk() is None


def test_html_masquerading_as_pdf_content_type_is_rejected(stub_httpx, caplog):
    """The inverse: a text/html body labelled application/pdf is not a PDF."""
    stub_httpx(_Resp(b"<html><body>Access denied</body></html>"))

    with caplog.at_level(logging.WARNING, logger="hyperresearch.pdf"):
        assert provider._fetch_pdf("https://example.com/x.pdf") is None

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
        assert provider._fetch_pdf("https://example.com/scan.pdf") is None

    assert "no extractable text layer" in caplog.text
    assert "OCR" in caplog.text
