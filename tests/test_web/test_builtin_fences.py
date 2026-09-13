"""The builtin provider must not flatten fetched code to prose.

Flattened <pre>/<code> content passes the note parser's code-strip untouched
and reaches WIKI_LINK_RE, where bash test syntax is lexically a wiki-link;
repair/graph then materialise junk stub notes named after shell fragments
(40 such notes in one real vault, all fetched via this provider). These
tests pin markdown-shaped code handling in BOTH extraction branches: bs4
and the stdlib fallback.
"""

import pytest

from hyperresearch.core.patterns import (
    CODE_BLOCK_RE,
    INLINE_CODE_RE,
    WIKI_LINK_RE,
    is_valid_wiki_link_target,
)
from hyperresearch.web.builtin import BuiltinProvider, _TextExtractor
from hyperresearch.web.pdf import PDF_FAILURE_KEY
from hyperresearch.web.safe_http import SafeResponse

# Shaped like the real defect page (a wiki page whose body carries a shell
# script in <pre> plus a conditional in inline <code>, both with [[ ]] test
# syntax).
ARCH_WIKI_SHAPED = """<html><head><title>Secure Boot - ArchWiki</title></head>
<body><main>
<p>Create the following file and make it executable:</p>
<pre>#!/usr/bin/env bash

kernel="$1"
[[ -n "$kernel" ]] || exit 0

# use already installed kernel if it exists
[[ ! -f "$KERNELDESTINATION" ]] || kernel="$KERNELDESTINATION"</pre>
<p>Then check <code>[[ -f /boot/vmlinuz ]]</code> before rebooting.</p>
</main></body></html>"""


def _surviving_links(text: str) -> list[str]:
    """The exact strip-then-extract sequence core/note.py runs on a note body."""
    cleaned = CODE_BLOCK_RE.sub("", text)
    cleaned = INLINE_CODE_RE.sub("", cleaned)
    raw = (m.group(1).strip().rstrip("\\") for m in WIKI_LINK_RE.finditer(cleaned))
    return [ref for ref in raw if is_valid_wiki_link_target(ref)]


class _BranchContract:
    """Shared assertions; subclasses supply the extraction branch."""

    def extract(self, html: str) -> tuple[str, str]:
        raise NotImplementedError

    def test_pre_becomes_fenced_block(self):
        _, text = self.extract(ARCH_WIKI_SHAPED)
        assert "```" in text
        assert '[[ -n "$kernel" ]] || exit 0' in text

    def test_inline_code_becomes_backtick_span(self):
        _, text = self.extract(ARCH_WIKI_SHAPED)
        assert "`[[ -f /boot/vmlinuz ]]`" in text

    def test_no_wiki_links_survive_the_note_strip(self):
        # The end-to-end guarantee the fix exists for: after the exact
        # code-strip the link extractor applies, no [[ ]] fragment remains.
        _, text = self.extract(ARCH_WIKI_SHAPED)
        assert _surviving_links(text) == []

    def test_code_indentation_survives(self):
        html = "<html><body><p>x</p><pre>if x:\n    do_thing()</pre></body></html>"
        _, text = self.extract(html)
        assert "    do_thing()" in text

    def test_fence_outgrows_backticks_inside_code(self):
        html = "<html><body><pre>echo ```already fenced```</pre></body></html>"
        _, text = self.extract(html)
        assert "````" in text
        assert _surviving_links(text) == []

    def test_title_and_noise_removal_unchanged(self):
        html = (
            "<html><head><title>T</title></head><body>"
            "<nav>menu here</nav><p>body text</p><footer>foot here</footer>"
            "</body></html>"
        )
        title, text = self.extract(html)
        assert title == "T"
        assert "menu here" not in text
        assert "foot here" not in text
        assert "body text" in text


class TestBs4Branch(_BranchContract):
    def extract(self, html: str) -> tuple[str, str]:
        pytest.importorskip("bs4")
        return BuiltinProvider()._extract(html)


class TestStdlibBranch(_BranchContract):
    def extract(self, html: str) -> tuple[str, str]:
        parser = _TextExtractor()
        parser.feed(html)
        return parser._title, parser.get_text()


# fetch() is the only way content leaves the provider: HTML fetched directly,
# and HTML reached after the PDF lane declines a PDF-shaped URL. Both must go
# through the code-preserving extraction, and the decline reason must still
# travel with the result. The SSRF-gated download is stubbed at its source.


@pytest.fixture
def served(monkeypatch):
    table: dict[str, SafeResponse] = {}

    def fake_safe_get(url, *, max_bytes, timeout=None, headers=None, verify=True,
                      allow_private_hosts=()):
        return table[url]

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)
    monkeypatch.setattr("hyperresearch.web.safe_http.check_url", lambda url, allow=(): None)
    return table


def _html(url: str, body: str, status: int = 200) -> SafeResponse:
    return SafeResponse(url=url, status_code=status, headers={"content-type": "text/html"},
                        content=body.encode())


def test_fetch_html_lane_preserves_code(served):
    url = "https://wiki.example.org/title/Secure_Boot"
    served[url] = _html(url, ARCH_WIKI_SHAPED)

    result = BuiltinProvider().fetch(url)

    assert "```" in result.content
    assert _surviving_links(result.content) == []
    assert result.looks_like_junk() is None


def test_fetch_after_pdf_lane_decline_preserves_code_and_reason(served):
    abs_url = "https://arxiv.org/abs/2005.14165"
    pdf_url = "https://arxiv.org/pdf/2005.14165.pdf"
    served[pdf_url] = _html(pdf_url, "", status=403)
    served[abs_url] = _html(abs_url, ARCH_WIKI_SHAPED)

    result = BuiltinProvider().fetch(abs_url)

    assert result.metadata[PDF_FAILURE_KEY] == "HTTP 403"
    assert "```" in result.content
    assert _surviving_links(result.content) == []
