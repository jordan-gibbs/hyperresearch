"""Tests for wiki-link target validation — citation-footnote edge cases."""

from hyperresearch.core.patterns import is_valid_wiki_link_target, strip_code


def test_empty_and_whitespace_rejected():
    assert not is_valid_wiki_link_target("")
    assert not is_valid_wiki_link_target("   ")
    assert not is_valid_wiki_link_target("\n")


def test_urls_rejected():
    assert not is_valid_wiki_link_target("https://example.com/foo")
    assert not is_valid_wiki_link_target("http://example.com")
    assert not is_valid_wiki_link_target("ftp://files.example.com")
    assert not is_valid_wiki_link_target("mailto:jordan@example.com")


def test_anchors_and_paths_rejected():
    assert not is_valid_wiki_link_target("#section-1")
    assert not is_valid_wiki_link_target("/path/to/note")


def test_pure_numeric_citation_footnotes_rejected():
    # Past bug: Wikipedia footnotes rendered as [[100]] and got mistaken
    # for wiki-link targets.
    assert not is_valid_wiki_link_target("100")
    assert not is_valid_wiki_link_target("1")
    assert not is_valid_wiki_link_target("999")


def test_caret_prefixed_footnotes_rejected():
    # Markdown-standard footnote syntax
    assert not is_valid_wiki_link_target("^1")
    assert not is_valid_wiki_link_target("^100")


def test_multi_number_citations_rejected():
    # Comma/semicolon/dash-separated citation groups
    assert not is_valid_wiki_link_target("100,101")
    assert not is_valid_wiki_link_target("1, 2, 3")
    assert not is_valid_wiki_link_target("100; 101")
    assert not is_valid_wiki_link_target("1-5")
    assert not is_valid_wiki_link_target("100-105")


def test_cite_prefix_patterns_rejected():
    assert not is_valid_wiki_link_target("cite-1")
    assert not is_valid_wiki_link_target("cite_2")
    assert not is_valid_wiki_link_target("cite:3")
    assert not is_valid_wiki_link_target("ref-42")
    assert not is_valid_wiki_link_target("ref_42")
    assert not is_valid_wiki_link_target("fn-1")
    assert not is_valid_wiki_link_target("fn:2")
    assert not is_valid_wiki_link_target("note-5")
    assert not is_valid_wiki_link_target("footnote-10")
    assert not is_valid_wiki_link_target("endnote-3")


def test_cite_prefixes_are_case_insensitive():
    assert not is_valid_wiki_link_target("Cite-1")
    assert not is_valid_wiki_link_target("REF_2")
    assert not is_valid_wiki_link_target("Fn-3")


def test_space_separated_footnote_names_rejected():
    """HTML footnote rendering: <sup>Note 1</sup> → [[Note 1]]. Past
    runs produced stubs for these because the filter missed them."""
    assert not is_valid_wiki_link_target("Note 1")
    assert not is_valid_wiki_link_target("Note 2")
    assert not is_valid_wiki_link_target("Footnote 12")
    assert not is_valid_wiki_link_target("note 10")
    assert not is_valid_wiki_link_target("Endnote 3")
    assert not is_valid_wiki_link_target("Ref 42")


def test_valid_note_ids_accepted():
    # Real note IDs should pass through
    assert is_valid_wiki_link_target("pegasus-seiya")
    assert is_valid_wiki_link_target("the-comics-journal-soldier-dream")
    assert is_valid_wiki_link_target("quantum-computing")
    assert is_valid_wiki_link_target("scaffold-saint-seiya")


def test_note_ids_starting_with_digits_accepted():
    # [[10-rules-for-X]] or [[1984-novel]] must pass — they contain non-digit chars
    assert is_valid_wiki_link_target("10-rules-for-typescript")
    assert is_valid_wiki_link_target("1984-novel")
    assert is_valid_wiki_link_target("100-greatest-films")


def test_note_ids_that_contain_cite_word_accepted():
    # "citation" is not "cite-N" — should pass
    assert is_valid_wiki_link_target("citations-are-important")
    assert is_valid_wiki_link_target("references-guide")
    assert is_valid_wiki_link_target("note-taking-systems")  # plural, no digit


def test_whitespace_is_stripped():
    # Leading/trailing whitespace should be stripped before evaluation
    assert not is_valid_wiki_link_target("  100  ")
    assert not is_valid_wiki_link_target("\t^100\n")
    assert is_valid_wiki_link_target("  valid-note-id  ")


def test_roman_numeral_footnotes_rejected():
    # Academic papers use Roman numerals for appendix/preface footnotes.
    assert not is_valid_wiki_link_target("i")
    assert not is_valid_wiki_link_target("iv")
    assert not is_valid_wiki_link_target("xii")
    assert not is_valid_wiki_link_target("xxiv")
    assert not is_valid_wiki_link_target("IV")
    assert not is_valid_wiki_link_target("XIV")


def test_symbol_footnotes_rejected():
    # Typography-style footnote markers used in older academic publishing.
    assert not is_valid_wiki_link_target("*")
    assert not is_valid_wiki_link_target("**")
    assert not is_valid_wiki_link_target("†")
    assert not is_valid_wiki_link_target("‡")
    assert not is_valid_wiki_link_target("§")
    assert not is_valid_wiki_link_target("¶")


def test_document_cross_references_rejected():
    # Figure / table / equation refs are document-internal, not wiki-links.
    assert not is_valid_wiki_link_target("fig-3")
    assert not is_valid_wiki_link_target("figure-4b")
    assert not is_valid_wiki_link_target("tab-1")
    assert not is_valid_wiki_link_target("table-2")
    assert not is_valid_wiki_link_target("eq-2")
    assert not is_valid_wiki_link_target("equation-7")
    assert not is_valid_wiki_link_target("scheme-3")
    assert not is_valid_wiki_link_target("algorithm-2")
    assert not is_valid_wiki_link_target("Fig-1")  # case-insensitive


def test_real_words_that_look_like_roman_are_accepted():
    # "dim" and "mix" look roman-like but are real note ids
    assert is_valid_wiki_link_target("mix-matrix")
    assert is_valid_wiki_link_target("div-container")
    # Longer words containing roman chars are fine
    assert is_valid_wiki_link_target("civic")
    assert is_valid_wiki_link_target("minimalism")


# --- issue #93: [[Label]](url) is a markdown link, not a wiki-link ---------


def _targets(text: str) -> list[str]:
    from hyperresearch.core.patterns import WIKI_LINK_RE

    return [m.group(1) for m in WIKI_LINK_RE.finditer(text)]


def test_bracketed_markdown_link_label_is_not_a_wikilink():
    # GitHub READMEs / awesome-lists: the *label* is bracketed, the whole
    # thing is a markdown link. Must not be extracted as a wiki-link.
    assert _targets("[[Label]](https://example.com)") == []
    assert _targets("see [[100]](https://en.wikipedia.org/wiki/Foo#cite_note-100)") == []
    assert _targets("[[Some Repo|alias]](https://github.com/x/y)") == []


def test_wikilink_followed_by_spaced_parenthetical_still_matches():
    # A real wiki-link is never *immediately* followed by "(" — but a
    # parenthetical after a space is ordinary prose and must keep working.
    assert _targets("[[note]] (2024)") == ["note"]
    assert _targets("[[note|Display]] (see also)") == ["note"]
    # Mixed line: the markdown link is skipped, the real link survives.
    assert _targets("[[Label]](https://x) and [[real-note]]") == ["real-note"]


def test_template_placeholders_rejected():
    # Unsubstituted skill-prompt placeholders leaking into a note body.
    assert not is_valid_wiki_link_target("{note_id}")
    assert not is_valid_wiki_link_target("run-{vault_tag}")
    assert not is_valid_wiki_link_target("interim-report-{locus-name}")
    # Braces that are balanced-but-empty are still a placeholder shape.
    assert not is_valid_wiki_link_target("{}")


def test_unbalanced_brackets_rejected():
    # `[[t.IO[t.Any]]` — a type annotation whose closing "]" was eaten by
    # the "]]" delimiter; the captured ref has one "[" and no "]".
    assert not is_valid_wiki_link_target("t.IO[t.Any")
    assert not is_valid_wiki_link_target("list[str")
    assert not is_valid_wiki_link_target("foo]")
    # Balanced brackets inside an id are unusual but not a parse artifact.
    assert is_valid_wiki_link_target("array[0]-semantics")


def test_wikilink_scan_is_linear_on_bracket_floods():
    # Page bodies are attacker-controlled and this pattern runs on every
    # sync. With `[` admitted into the character classes every `[[` start
    # position ate to the end of the run before failing: ~20 s at 40 KB,
    # unbounded at 1 MB. Each flood below must finish in well under a second.
    import time

    floods = {
        "[": "[" * 300_000,
        "[[": "[[" * 150_000,
        "[[a": "[[a" * 100_000,
        "[[a|": "[[a|" * 75_000,
        "[[a|b": "[[a|b" * 60_000,
        "]](": "[[a]](" * 50_000,
    }
    for name, flood in floods.items():
        started = time.perf_counter()
        targets = _targets(flood)
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0, f"{name!r} flood took {elapsed:.2f}s"
        assert targets == [], name


def test_template_placeholder_check_is_linear():
    import time

    # Only the time is under test: an unclosed brace flood is not a
    # placeholder, so the verdict itself may legitimately be True.
    for flood in ("{" * 300_000, "{" + "a" * 300_000, "{a" * 150_000, "{a}" * 100_000):
        started = time.perf_counter()
        is_valid_wiki_link_target(flood)
        assert time.perf_counter() - started < 1.0


def test_code_strip_is_linear_on_backtick_floods():
    # Runs on every fetched body before link extraction (#140). A
    # backreference regex matching closing fences to opening ones re-scans
    # to the end of the text for every unclosed run: the staircase of
    # distinct, never-closed run lengths is the worst case for that shape.
    import time

    floods = {
        "`": "`" * 300_000,
        "```\\n": "```\n" * 75_000,
        "`a": "`a" * 150_000,
        "``` ": "``` " * 75_000,
        "unclosed ````": "````\n" + "```\n" * 75_000,
        "staircase": "".join("`" * n + "a" for n in range(1500, 0, -1)),
    }
    for name, flood in floods.items():
        started = time.perf_counter()
        strip_code(flood)
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0, f"{name!r} flood took {elapsed:.2f}s"


def test_interior_open_bracket_never_matches():
    # Previously matched as target `t.IO[t.Any` and was rejected downstream
    # by the bracket-balance check; now the pattern itself refuses it.
    assert _targets("[[t.IO[t.Any]]") == []
    assert _targets("[[list[str]]") == []
    # Extra leading brackets do not become part of the target.
    assert _targets("[[[x]]") == ["x"]
    # Ordinary links and aliases are untouched.
    assert _targets("[[note-id]] and [[other|Shown]]") == ["note-id", "other"]


def test_shell_fragments_rejected():
    # When a fetcher flattens <pre> content to prose, bash test syntax
    # reaches this extractor and is lexically a wiki-link; `repair` then
    # materialises junk notes named after shell fragments. Every shape below
    # passed the validator before this check. (`"${HOSTID}"`-style refs are
    # already rejected by the template-placeholder check.)
    assert not is_valid_wiki_link_target('-n "$kernel"')
    assert not is_valid_wiki_link_target('! -f "$KERNELDESTINATION"')
    assert not is_valid_wiki_link_target("$# -lt 1")
    assert not is_valid_wiki_link_target("-z foo")
    assert not is_valid_wiki_link_target("a=b")
    assert not is_valid_wiki_link_target("back`tick")
    assert not is_valid_wiki_link_target("x < y; rm")


def test_path_traversal_rejected():
    # Never a note reference, whatever downstream writes the file.
    assert not is_valid_wiki_link_target("../../../tmp/pwned")
    assert not is_valid_wiki_link_target("a/../../b")
    assert not is_valid_wiki_link_target("a/..")
    assert not is_valid_wiki_link_target("..")
    assert not is_valid_wiki_link_target(".")


def test_shell_shaped_but_legitimate_refs_still_accepted():
    # The net is partial BY DESIGN: shapes indistinguishable from real ids
    # pass, and titles with mid-string slashes or punctuation stay legal.
    assert is_valid_wiki_link_target("1-d")
    assert is_valid_wiki_link_target("hostid-00000000")
    assert is_valid_wiki_link_target("UEFI/Secure Boot")  # real wiki title shape
    assert is_valid_wiki_link_target("C. elegans")
    assert is_valid_wiki_link_target("yahoo! finance")  # '!' mid-string stays legal
    assert is_valid_wiki_link_target("e.g. v1.2")
