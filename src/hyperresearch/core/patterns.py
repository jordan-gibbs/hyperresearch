"""Shared regex patterns for wiki-link parsing."""

from __future__ import annotations

import re

# Match [[target]] and [[target|display text]]
WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Code block patterns for stripping before link extraction
CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]+`")


# Citation-footnote patterns that should NOT be treated as wiki-links even
# though crawl4ai sometimes renders them as [[100]] or [[^100]] in fetched
# markdown. These originate from Wikipedia-style footnote markup like
# `[[100]](https://en.wikipedia.org/wiki/Foo#cite_note-100)` where the
# visible text is the citation number in brackets.
_CITATION_FOOTNOTE_RE = re.compile(
    r"^\^?\d+(?:[\s,;\-]+\d+)*$"
)

# Explicit citation prefixes: [[cite-1]], [[ref_2]], [[fn:3]], [[note-4]],
# [[Note 1]], [[Footnote 12]]. The space-separated variant ("Note 1") leaks
# from HTML footnote rendering where <sup>Note 1</sup> gets turned into
# wiki-link syntax by crawl4ai. Separator class now includes whitespace.
_CITE_PREFIX_RE = re.compile(
    r"^(?:cite|ref|note|fn|footnote|endnote)[\s_:-]*\d+$",
    re.IGNORECASE,
)

# Roman-numeral footnotes: [[iv]], [[xii]], [[ccxliv]] (lowercase or upper).
# Academic papers use these for appendices and preface footnotes. Uses the
# standard Roman-numeral grammar (not just "chars in [ivxlcdm]") so real
# words like "civic" or "mix" don't match by accident. The empty string is
# explicitly excluded — it would otherwise match M{0}X{0}I{0}.
_ROMAN_FOOTNOTE_RE = re.compile(
    r"^(?=[ivxlcdm])M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)

# Symbol footnotes: [[*]], [[**]], [[†]], [[‡]], [[§]], [[¶]], [[#]], [[△]].
# Typography-style footnote markers used in older academic publishing.
_SYMBOL_FOOTNOTE_RE = re.compile(
    r"^[\*\u2020\u2021\u00a7\u00b6#\u25b3\u25bd]{1,3}$"
)

# Figure / table / equation references: [[fig-3]], [[tab-1]], [[eq-2]],
# [[table1]], [[figure-4b]], [[eq:7]], [[scheme-3]]. These are cross-
# references within a document, not wiki-links to other notes.
_DOC_REF_PREFIX_RE = re.compile(
    r"^(?:fig(?:ure)?|tab(?:le)?|eq(?:uation)?|scheme|chart|plate|box|chart|algo(?:rithm)?)[-_:]?\w*$",
    re.IGNORECASE,
)


def is_valid_wiki_link_target(ref: str) -> bool:
    """Return True if a ``[[ref]]`` should be treated as a note reference.

    Filters out content that crawl4ai and other markdown fetchers sometimes
    produce as double-bracket targets but that should NOT resolve to notes:

    - Empty / whitespace-only refs
    - URLs (``http://``, ``https://``, ``ftp://``, ``mailto:``)
    - Anchors (``#section-id``) and absolute paths (``/path/to/thing``)
    - Pure-numeric citation footnotes: ``[[100]]``, ``[[^100]]``,
      ``[[100,101]]``, ``[[1-5]]``, ``[[100; 101]]``
    - Explicit citation prefixes: ``[[cite-1]]``, ``[[ref_2]]``, ``[[fn:3]]``,
      ``[[note-4]]``, ``[[footnote-5]]``, ``[[Note 1]]``, ``[[Footnote 12]]``
    - Roman-numeral footnotes: ``[[iv]]``, ``[[xii]]``
    - Symbol footnotes: ``[[*]]``, ``[[**]]``, ``[[†]]``, ``[[‡]]``, ``[[§]]``
    - Document cross-references: ``[[fig-3]]``, ``[[tab-1]]``, ``[[eq-2]]``,
      ``[[figure-4b]]``, ``[[scheme-3]]``, ``[[algorithm-2]]``

    Valid note references starting with digits (e.g. ``[[10-rules-for-X]]``)
    are preserved because they contain non-digit characters.
    """
    if not ref:
        return False
    ref = ref.strip()
    if not ref:
        return False
    if ref.startswith(("http://", "https://", "ftp://", "mailto:", "#", "/")):
        return False
    if _CITATION_FOOTNOTE_RE.match(ref):
        return False
    if _CITE_PREFIX_RE.match(ref):
        return False
    if _ROMAN_FOOTNOTE_RE.match(ref):
        return False
    if _SYMBOL_FOOTNOTE_RE.match(ref):
        return False
    return not _DOC_REF_PREFIX_RE.match(ref)
