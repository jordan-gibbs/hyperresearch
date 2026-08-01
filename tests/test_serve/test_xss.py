"""The wiki serves note bodies, and note bodies are fetched remote pages.

`core/untrusted.py` already treats those as hostile on the CLI read paths. These
tests hold the viewer to the same assumption (#72).
"""

import html as html_mod

import pytest

from hyperresearch.core.note import strip_markdown
from hyperresearch.serve.renderer import _is_safe_url, render_markdown


def _render_snippet(raw: str) -> str:
    """The exact transform `_serve_search` applies to an FTS snippet."""
    return (
        html_mod.escape(raw)
        .replace("&gt;&gt;&gt;", "<mark>")
        .replace("&lt;&lt;&lt;", "</mark>")
    )


class TestSearchSnippet:
    def test_unterminated_tag_cannot_borrow_the_mark_closer(self):
        """strip_markdown's tag regex needs a closing '>', so an unterminated
        tag survives into body_plain intact. Substituting the markers before
        escaping then handed it the '>' it was missing, off the </mark>."""
        body = "trigger <img src=x onerror=alert(document.domain) text"
        assert strip_markdown(body) == body, "premise: strip_markdown lets this through"

        out = _render_snippet(">>>trigger<<< <img src=x onerror=alert(document.domain) text")

        assert "<img" not in out
        assert "onerror" not in out.replace("&lt;img src=x onerror", "")
        assert "&lt;img" in out

    @pytest.mark.parametrize(
        "payload",
        [
            "<script>alert(1)</script>",
            "<svg onload=alert(1)>",
            "\"><script>alert(1)</script>",
            "<iframe src=javascript:alert(1)",
        ],
    )
    def test_no_payload_survives_as_markup(self, payload):
        out = _render_snippet(f">>>hit<<< {payload}")
        assert "<script" not in out
        assert "<svg" not in out
        assert "<iframe" not in out

    def test_markers_still_become_mark_tags(self):
        out = _render_snippet("the >>>term<<< in context")
        assert out == "the <mark>term</mark> in context"

    def test_literal_entity_text_is_not_mistaken_for_a_marker(self):
        """A body containing the literal text '&gt;&gt;&gt;' must not turn into
        a <mark>, since escaping rewrites its '&' first."""
        out = _render_snippet("literal &gt;&gt;&gt; here")
        assert "<mark>" not in out


class TestUrlSchemes:
    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "  javascript:alert(1)",
            "java\tscript:alert(1)",
            "java\nscript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "vbscript:msgbox(1)",
        ],
    )
    def test_dangerous_schemes_render_as_plain_text(self, url):
        assert not _is_safe_url(url)
        out = render_markdown(f"see [click me]({url}) here")
        assert "<a href" not in out
        assert "click me" in out

    def test_entity_encoded_scheme_is_caught(self):
        """A browser resolves `&#106;avascript:` back to `javascript:` when it
        parses the attribute. render_markdown happens to escape the '&' before
        the URL reaches here, so this is belt-and-braces for any other caller."""
        assert not _is_safe_url("&#106;avascript:alert(1)")

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/paper",
            "http://example.com",
            "mailto:someone@example.com",
            "/note/some-id",
            "#section",
            "relative/path.md",
            "//cdn.example.com/x.png",
        ],
    )
    def test_ordinary_links_still_render(self, url):
        assert _is_safe_url(url)
        assert f'<a href="{url}">' in render_markdown(f"[label]({url})")

    def test_body_text_is_still_escaped(self):
        out = render_markdown("<script>alert(1)</script>")
        assert "<script>" not in out
