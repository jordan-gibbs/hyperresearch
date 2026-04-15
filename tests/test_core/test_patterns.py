"""Tests for wiki-link target validation — citation-footnote edge cases."""

from hyperresearch.core.patterns import is_valid_wiki_link_target


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
    # The Q91 bug: Wikipedia footnotes rendered as [[100]]
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
