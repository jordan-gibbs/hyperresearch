"""Shared regex patterns for wiki-link parsing."""

from __future__ import annotations

import re

# Match [[target]] and [[target|display text]].
#
# The trailing `(?!\()` rejects `[[Label]](https://url)` — a markdown link
# whose *label* happens to be bracketed, common on GitHub READMEs,
# awesome-lists and Wikipedia-style footnotes (`[[100]](…#cite_note-100)`).
# Without it every such label becomes a wiki-link target, sync writes it to
# the `links` table, and `repair` / `graph stub` mint a stub note for it. A
# real wiki-link is never immediately followed by `(`; a parenthetical
# after a space (`[[note]] (2024)`) still matches (issue #93).
#
# Neither character class admits `[`. Page bodies are attacker-controlled
# and this runs on every sync: with `[` allowed, a line of N `[` characters
# made every `[[` start position eat to the end of the run before failing —
# quadratic, ~20 s at 40 KB and unbounded at 1 MB. Excluding `[` makes a
# candidate fail at its first extra bracket, so scanning is linear. A target
# with an interior `[` (`[[t.IO[t.Any]]`) was already rejected downstream by
# is_valid_wiki_link_target's bracket-balance check; now it never matches.
WIKI_LINK_RE = re.compile(r"\[\[([^\]\[|]+)(?:\|[^\]\[]+)?\]\](?!\()")

# --- Code stripping before link extraction and indexing ---------------------
#
# Code must be removed before WIKI_LINK_RE runs: bash test syntax
# (`[[ -n "$k" ]]`) is lexically a wiki-link. This used to be two regexes,
# ```.*?``` and `[^`]+`, which closed every span at the first backtick run
# of any length. The builtin provider (#129) fences code with a run longer
# than any inside it, as CommonMark requires, so code holding an odd number
# of ``` ended the block early and leaked its [[ ]] into the parser (#140).
#
# The rules follow CommonMark where it matters here:
#
# - A fenced block opens on a line whose first non-blank characters are 3+
#   backticks with no backtick after them, and closes on a line holding
#   only a run of AT LEAST that many backticks. Unclosed, it runs to the end
#   of the text: better to lose links after a broken fence than to parse
#   code as links. Any indentation is accepted (fences inside list items).
#   Tilde fences are not recognised, as before.
# - An inline span opened by N backticks closes at the next run of EXACTLY
#   N backticks; an unmatched run is literal text. Spans may cross lines,
#   as the old regex allowed. Backtick runs that are not fences (mid-line
#   ```x```, a line-start run followed by more backticks) are inline runs.
#
# Fetched bodies are attacker-controlled and this runs on every sync, so
# it is a scanner, not a regex: a backreference regex re-scans to the end
# of the text for every unclosed run and goes superlinear on backtick
# floods. Both passes below are linear.
#
# Stripped code is replaced by the newlines it held (a space for a span
# on one line), so sync's per-line link numbers stay true and text on
# either side of a span cannot fuse into a new `[[`.

_BACKTICK_RUN_RE = re.compile(r"`+")


def _strip_fenced_blocks(text: str) -> str:
    out: list[str] = []
    fence = 0  # length of the open fence's backtick run; 0 = not in a block
    for line in text.split("\n"):
        s = line.lstrip(" \t")
        run = len(s) - len(s.lstrip("`"))
        if fence:
            if run >= fence and not s[run:].strip(" \t\r"):
                fence = 0
            out.append("")
        elif run >= 3 and "`" not in s[run:]:
            fence = run
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def _strip_inline_code(text: str) -> str:
    runs = [m.span() for m in _BACKTICK_RUN_RE.finditer(text)]
    if len(runs) < 2:
        return text
    # Run indices grouped by length; each group's cursor only moves forward,
    # so finding every closer costs O(runs) in total.
    by_len: dict[int, list[int]] = {}
    for i, (a, b) in enumerate(runs):
        by_len.setdefault(b - a, []).append(i)
    cursor = dict.fromkeys(by_len, 0)

    out: list[str] = []
    pos = 0
    i = 0
    while i < len(runs):
        a, b = runs[i]
        n = b - a
        group = by_len[n]
        k = cursor[n]
        while k < len(group) and group[k] <= i:
            k += 1
        cursor[n] = k
        if k == len(group):
            i += 1  # no closer: the run is literal text
            continue
        j = group[k]
        end = runs[j][1]
        newlines = text.count("\n", a, end)
        out.append(text[pos:a])
        out.append("\n" * newlines if newlines else " ")
        pos = end
        i = j + 1
    out.append(text[pos:])
    return "".join(out)


def strip_code(text: str) -> str:
    """Remove fenced code blocks, then inline code spans, from markdown.

    Run this before WIKI_LINK_RE so code is never parsed as links. Linear in
    the length of the text, including on backtick floods.
    """
    return _strip_inline_code(_strip_fenced_blocks(text))


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


# Unsubstituted template placeholders: [[{note_id}]], [[run-{vault_tag}]].
# Skill prompts and agent scaffolds carry these literally; when one leaks
# into a note body it must not become a link target (issue #93).
_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")

# Shell/code fragments: characters that code in fetched pages carries but no
# legitimate note id or title does. Bash test syntax ([[ -n "$kernel" ]]) is
# lexically a wiki-link, so when a fetcher flattens <pre> content to prose,
# every shell conditional becomes a broken link that `repair` / `graph stub`
# then materialise as a junk note. Braces are left to the placeholder check
# above, which already rejects `${VAR}`. This is a PARTIAL net by design:
# refs shaped like real ids (`1-d`, `hostid-00000000`) pass.
_SHELL_FRAGMENT_CHARS_RE = re.compile(r'[$"`=\\<>;]')


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
    - Unsubstituted template placeholders: ``[[{note_id}]]``, ``[[run-{tag}]]``
    - Unbalanced square brackets: ``[[t.IO[t.Any]]`` (a type annotation whose
      closing ``]`` was eaten by the ``]]`` delimiter)
    - Shell fragments: ``[[-n "$kernel"]]``, ``[[! -f x]]``, ``[[a=b]]`` (bash
      test syntax from flattened code blocks: a leading ``-`` or ``!``, or a
      shell metacharacter no note id or title carries)
    - Path traversal: ``[[../../x]]``, ``[[a/../b]]``, ``[[..]]``

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
    if _TEMPLATE_PLACEHOLDER_RE.search(ref):
        return False
    if _SHELL_FRAGMENT_CHARS_RE.search(ref):
        return False
    # Leading '-' or '!' is option/negation syntax (`-n "$kernel"`,
    # `! -f x`), not a reference. Mid-string they stay legal (titles).
    if ref.startswith(("-", "!")):
        return False
    # Path traversal: never a note reference, whatever writes the file.
    if any(part in ("..", ".") for part in ref.split("/")):
        return False
    if ref.count("[") != ref.count("]"):
        return False
    return not _DOC_REF_PREFIX_RE.match(ref)
