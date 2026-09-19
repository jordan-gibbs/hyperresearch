"""PDF lane shared by every web provider.

Detects PDF URLs, downloads them through the SSRF gate, and extracts text
with pymupdf. This used to live inside the crawl4ai provider only, so a
vault on the builtin provider had no PDF handling at all: a direct .pdf
link was decoded as HTML text and rejected by the junk gate as "Binary PDF
garbage in content", identically for every mirror of the same document,
and an arXiv /abs/ link saved the abstract page instead of the paper (#82).

Every failure path here produces a reason string. Providers carry that
reason on the fallback result's ``metadata["pdf_failure"]`` so the CLI can
print it next to the junk verdict instead of a bare generic message.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from hyperresearch.core.config import FetchSettings
from hyperresearch.web.base import WebResult

# Key under which a provider records why the PDF lane declined a URL when it
# then falls back to the HTML lane. Read by `hpr fetch` when the fallback
# result turns out to be junk.
PDF_FAILURE_KEY = "pdf_failure"

_PYMUPDF_MISSING_LOGGED = False


def pdf_log() -> logging.Logger:
    return logging.getLogger("hyperresearch.pdf")


def is_pdf_url(url: str) -> bool:
    """Check if URL likely points to a PDF."""
    from urllib.parse import urlparse

    parsed = urlparse(url.lower())
    path = parsed.path
    # Direct .pdf links
    if path.endswith(".pdf"):
        return True
    # Common academic PDF patterns
    if "/pdf/" in path or "/pdfs/" in path:
        return True
    # arXiv PDF links
    return "arxiv.org" in parsed.netloc and ("/pdf/" in path or "/abs/" in path)


def import_pymupdf():
    """Import pymupdf, warning loudly (once) if it is unavailable.

    Without this warning a missing/broken pymupdf is invisible: every PDF falls
    through to the HTML lane, arrives as binary, and is discarded as junk —
    across every domain at once, with nothing explaining why.
    """
    global _PYMUPDF_MISSING_LOGGED
    try:
        import pymupdf

        return pymupdf
    except ImportError as exc:
        if not _PYMUPDF_MISSING_LOGGED:
            _PYMUPDF_MISSING_LOGGED = True
            pdf_log().error(
                "pymupdf could not be imported (%s) — PDF text extraction is disabled, "
                "so every PDF will be discarded as junk content. Reinstall it with "
                "`pip install --force-reinstall pymupdf`.",
                exc,
            )
        return None


PDF_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
}


def _is_cert_error(exc: Exception) -> bool:
    import ssl

    # httpx nests the ssl error two causes deep (httpx.ConnectError ->
    # httpcore.ConnectError -> SSLCertVerificationError), so walk the chain
    # rather than checking only the direct cause. String match as fallback.
    cause: BaseException | None = exc
    for _ in range(5):
        if cause is None:
            break
        if isinstance(cause, ssl.SSLCertVerificationError):
            return True
        cause = cause.__cause__
    return "CERTIFICATE_VERIFY_FAILED" in str(exc)


def safe_get_pdf(url: str, settings: FetchSettings):
    """SSRF-gated, size-capped PDF download.

    TLS verification follows ``pdf_verify_tls`` (default on) with NO
    automatic unverified retry: a MITM can serve a bad certificate
    precisely to force such a retry, which would turn verify-by-default
    into something the attacker controls. Mirrors with known-broken
    certificates are handled by the explicit, user-declared
    ``pdf_verify_tls = false`` opt-out.
    """
    from hyperresearch.web.safe_http import CertVerificationError, safe_get

    try:
        return safe_get(url, max_bytes=settings.max_pdf_bytes,
                        timeout=settings.pdf_timeout_s,
                        headers=PDF_FETCH_HEADERS,
                        verify=settings.pdf_verify_tls,
                        allow_private_hosts=settings.allow_private_hosts)
    except Exception as exc:
        if settings.pdf_verify_tls and _is_cert_error(exc):
            # Refuse, but say how to opt out for a trusted cert-broken mirror.
            # Raised as its own type: the browser lane runs with TLS errors
            # ignored, so treating this like any failed PDF would hand the
            # URL to a lane that amounts to an automatic unverified retry.
            raise CertVerificationError(
                f"certificate verification failed for {url!r}: {exc}. "
                "If this host is a known cert-broken mirror you trust, set "
                "pdf_verify_tls = false under [fetch] in config.toml."
            ) from exc
        raise


def pdf_url_for(url: str) -> str:
    """The URL the PDF lane actually downloads: arXiv abs links become pdf links."""
    if "arxiv.org/abs/" in url:
        url = url.replace("/abs/", "/pdf/")
        if not url.endswith(".pdf"):
            url += ".pdf"
    return url


def extract_pdf(
    url: str,
    pdf_bytes: bytes,
    settings: FetchSettings | None = None,
    content_type: str = "",
) -> tuple[WebResult | None, str | None]:
    """Extract text from downloaded bytes. Returns (result, None) or (None, reason).

    Magic bytes are authoritative. Servers mislabel PDFs as octet-stream, and
    plenty of PDF URLs carry no .pdf suffix, so trusting the header or the URL
    shape alone silently drops real PDFs.
    """
    settings = settings or FetchSettings()
    log = pdf_log()

    pymupdf = import_pymupdf()
    if pymupdf is None:
        return None, "pymupdf is not importable"

    if not pdf_bytes.startswith(b"%PDF-"):
        reason = (
            f"did not return PDF data (content-type={content_type!r}, "
            f"first bytes={pdf_bytes[:8]!r})"
        )
        log.warning("PDF fetch for %s %s", url, reason)
        return None, reason

    if len(pdf_bytes) < settings.min_pdf_bytes:
        reason = f"returned only {len(pdf_bytes)} bytes"
        log.warning("PDF fetch for %s %s", url, reason)
        return None, reason

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        reason = f"pymupdf could not open the document: {e}"
        log.warning("PDF fetch for %s: %s", url, reason)
        return None, reason

    # Extract text from all pages. The handle is closed on the way out even
    # when page iteration raises (encrypted or damaged documents), which used
    # to leak one open document per failed PDF.
    pages = []
    try:
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages.append(text)
        page_count = doc.page_count
    except Exception as e:
        reason = f"pymupdf failed while reading pages: {e}"
        log.warning("PDF fetch for %s: %s", url, reason)
        return None, reason
    finally:
        doc.close()

    if not pages:
        reason = (
            f"has {page_count} page(s) but no extractable text layer — "
            "likely a scanned document requiring OCR"
        )
        log.warning("PDF at %s %s.", url, reason)
        return None, reason

    # Build markdown from extracted text
    full_text = "\n\n---\n\n".join(pages)
    title = ""
    # Try to get title from first page (first non-empty line)
    for line in pages[0].split("\n"):
        line = line.strip()
        if len(line) > 10:
            title = line
            break

    return WebResult(
        url=url,
        title=title or f"PDF: {url.split('/')[-1]}",
        content=full_text,
        fetched_at=datetime.now(UTC),
        metadata={"content_type": "application/pdf", "pages": len(pages)},
        raw_bytes=pdf_bytes,
        raw_content_type="application/pdf",
    ), None


def fetch_pdf_ex(
    url: str, settings: FetchSettings | None = None,
) -> tuple[WebResult | None, str | None]:
    """Download a PDF and extract its text. Returns (result, None) or (None, reason).

    The reason is a short phrase suitable for showing next to a junk verdict
    ("HTTP 403", "no extractable text layer"). A silent None here is
    indistinguishable from "this URL is not a PDF", which is what made
    missing-PDF failures so hard to diagnose.

    A certificate refusal propagates as ``CertVerificationError``: callers
    must not fold it into the generic failure, whose fallback is the
    TLS-ignoring browser lane.
    """
    from hyperresearch.web.safe_http import CertVerificationError, SafeHTTPError

    settings = settings or FetchSettings()
    log = pdf_log()

    if import_pymupdf() is None:
        return None, "pymupdf is not importable"

    url = pdf_url_for(url)
    try:
        try:
            resp = safe_get_pdf(url, settings)
        except CertVerificationError:
            raise
        except SafeHTTPError as exc:
            log.warning("refused PDF fetch for %s: %s", url, exc)
            return None, f"refused: {exc}"

        if resp.status_code != 200:
            log.warning("PDF fetch for %s returned HTTP %s", url, resp.status_code)
            return None, f"HTTP {resp.status_code}"

        return extract_pdf(url, resp.content, settings, resp.headers.get("content-type", ""))

    except CertVerificationError:
        # Second guard: the catch-all below must not convert a cert refusal
        # into the generic failure either.
        raise
    except Exception as e:
        log.warning("PDF extraction failed for %s: %s", url, e)
        return None, f"extraction failed: {e}"


# Why the PDF lane last declined each URL, keyed by the URL as requested.
# Providers call `fetch_pdf` (the patchable, result-only entry point) and read
# the reason back through `failure_reason` when they fall back to HTML.
_FAILURES: dict[str, str] = {}
_FAILURES_MAX = 256


def fetch_pdf(url: str, settings: FetchSettings | None = None) -> WebResult | None:
    """Download a PDF and extract text using pymupdf. Returns None if extraction fails.

    Result-only form of :func:`fetch_pdf_ex`. The failure reason is kept and
    can be read back with :func:`failure_reason`.
    """
    result, reason = fetch_pdf_ex(url, settings)
    if reason is not None:
        if len(_FAILURES) >= _FAILURES_MAX:
            _FAILURES.clear()
        _FAILURES[url] = reason
    else:
        _FAILURES.pop(url, None)
    return result


def failure_reason(url: str) -> str | None:
    """Why the last `fetch_pdf` for this URL returned None, if it did."""
    return _FAILURES.get(url)
