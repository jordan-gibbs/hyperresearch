"""The builtin provider has a PDF lane (#82).

Before this, `_fetch_pdf` lived inside the crawl4ai provider only. A vault on
`provider = "builtin"` (the default until `hpr install` switches it) decoded
every PDF as HTML text and the junk gate rejected it as "Binary PDF garbage
in content" — the same message for every mirror of the same document, which
is exactly the all-hosts-at-once shape reported in #82. An arXiv /abs/ link
saved the abstract page instead of the paper.

Offline: the SSRF-gated download (`safe_get`) is stubbed at the source, so
both the PDF lane and the HTML lane see canned responses.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web import pdf as pdf_lane
from hyperresearch.web.builtin import BuiltinProvider
from hyperresearch.web.safe_http import SafeResponse

runner = CliRunner()

HTML_PAGE = (
    "<html><head><title>[2005.14165] Language Models are Few-Shot Learners</title></head>"
    "<body><h1>Abstract</h1><p>" + "We demonstrate that scaling language models improves few-shot performance. " * 12
    + "</p></body></html>"
)


@pytest.fixture
def pdf_bytes() -> bytes:
    pytest.importorskip("pymupdf")
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((36, 60), "Language Models are Few-Shot Learners: full paper text.")
    for i in range(20):
        page.insert_text((36, 80 + i * 14), f"Line {i}: body text of the paper for extraction. " * 2)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def responses(monkeypatch):
    """Route every safe_get through a table of URL -> SafeResponse. Records requests."""
    table: dict[str, SafeResponse] = {}
    seen: list[str] = []

    def fake_safe_get(url, *, max_bytes, timeout=None, headers=None, verify=True,
                      allow_private_hosts=()):
        seen.append(url)
        if url not in table:
            raise AssertionError(f"unexpected fetch of {url}")
        return table[url]

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)
    # Keep the SSRF hostname check offline.
    monkeypatch.setattr("hyperresearch.web.safe_http.check_url", lambda url, allow=(): None)
    table["__seen__"] = seen  # type: ignore[assignment]
    return table


def _resp(url: str, body: bytes, content_type: str, status: int = 200) -> SafeResponse:
    return SafeResponse(url=url, status_code=status, headers={"content-type": content_type}, content=body)


def test_direct_pdf_url_is_extracted_not_decoded_as_html(responses, pdf_bytes):
    url = "https://mirror.example.org/papers/2005.14165.pdf"
    responses[url] = _resp(url, pdf_bytes, "application/pdf")

    result = BuiltinProvider().fetch(url)

    assert result.raw_content_type == "application/pdf"
    assert "full paper text" in result.content
    assert result.looks_like_junk() is None


def test_arxiv_abs_link_fetches_the_paper_not_the_abstract_page(responses, pdf_bytes):
    abs_url = "https://arxiv.org/abs/2005.14165"
    pdf_url = "https://arxiv.org/pdf/2005.14165.pdf"
    responses[abs_url] = _resp(abs_url, HTML_PAGE.encode(), "text/html")
    responses[pdf_url] = _resp(pdf_url, pdf_bytes, "application/pdf")

    result = BuiltinProvider().fetch(abs_url)

    assert responses["__seen__"] == [pdf_url], "the abs page must not be fetched at all"
    assert "full paper text" in result.content
    assert result.metadata.get("pages") == 1


def test_pdf_lane_failure_falls_back_to_html_and_carries_the_reason(responses):
    abs_url = "https://arxiv.org/abs/2005.14165"
    pdf_url = "https://arxiv.org/pdf/2005.14165.pdf"
    responses[pdf_url] = _resp(pdf_url, b"", "text/html", status=403)
    responses[abs_url] = _resp(abs_url, HTML_PAGE.encode(), "text/html")

    result = BuiltinProvider().fetch(abs_url)

    assert "Few-Shot Learners" in result.title
    assert result.metadata[pdf_lane.PDF_FAILURE_KEY] == "HTTP 403"


def test_pdf_behind_a_non_pdf_url_is_detected_from_the_bytes(responses, pdf_bytes):
    url = "https://repo.example.edu/download?id=123"
    responses[url] = _resp(url, pdf_bytes, "application/octet-stream")

    result = BuiltinProvider().fetch(url)

    assert result.raw_content_type == "application/pdf"
    assert "full paper text" in result.content


def test_cli_junk_verdict_names_the_pdf_lane_reason(tmp_path, responses, monkeypatch):
    """A PDF whose lane failed used to surface only as 'Binary PDF garbage in
    content' with no hint of why. The -j error now says what the PDF lane saw."""
    root = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(root), "--name", "PDF Test"]).exit_code == 0
    monkeypatch.chdir(root)

    url = "https://mirror.example.org/papers/x.pdf"
    calls = {"n": 0}

    def two_lanes(url_, *, max_bytes, timeout=None, headers=None, verify=True, allow_private_hosts=()):
        calls["n"] += 1
        if calls["n"] == 1:
            # PDF lane: the mirror answers with an HTML interstitial.
            return _resp(url_, b"<html>Access denied</html>", "text/html")
        # HTML lane: the same mirror now streams the raw document, which the
        # provider decodes as text and the junk gate calls binary garbage.
        return _resp(url_, bytes(range(256)) * 8, "text/html")

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", two_lanes)

    result = runner.invoke(app, ["fetch", url, "-j"])
    payload = json.loads(result.stdout)

    assert payload["ok"] is False
    assert payload["error_code"] == "JUNK_CONTENT"
    assert "PDF lane: did not return PDF data" in payload["error"]
    assert "text/html" in payload["error"]
