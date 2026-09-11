"""Cross-provider merge rules.

Every assertion here is about a duplicate that naive concatenation would have
left in the corpus, or a field that the wrong provider would have won.
"""

from __future__ import annotations

from hyperresearch.scholar.base import Paper
from hyperresearch.scholar.dedup import merge_papers

PRECEDENCE = ["openalex", "crossref", "core"]


def paper(source: str, title: str = "Attention Is All You Need", **kwargs: object) -> Paper:
    return Paper(title=title, source=source, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_matches_on_normalized_doi_despite_different_titles() -> None:
    """The DOI is authoritative: providers title the same work differently."""
    papers = [
        paper("openalex", "Attention Is All You Need", doi="10.5555/ABC.123"),
        paper("crossref", "Attention is all you need.", doi="https://doi.org/10.5555/abc.123"),
    ]
    merged = merge_papers(papers, PRECEDENCE)
    assert len(merged) == 1
    assert merged[0].source == "openalex"


def test_different_dois_never_merge_even_with_identical_titles() -> None:
    papers = [
        paper("openalex", doi="10.1/aaa", year=2017),
        paper("crossref", doi="10.1/bbb", year=2017),
    ]
    assert len(merge_papers(papers, PRECEDENCE)) == 2


def test_matches_on_title_and_year_when_a_doi_is_missing() -> None:
    papers = [
        paper("openalex", "Deep Residual Learning", year=2016),
        paper("crossref", "deep residual learning!", year=2016, doi="10.1/x"),
    ]
    merged = merge_papers(papers, PRECEDENCE)
    assert len(merged) == 1
    assert merged[0].doi == "10.1/x"


def test_year_tolerance_of_one_absorbs_online_first_versus_print() -> None:
    papers = [
        paper("openalex", "A Study Of Things", year=2020),
        paper("crossref", "A study of things", year=2021),
    ]
    assert len(merge_papers(papers, PRECEDENCE)) == 1


def test_year_gap_of_two_stays_separate() -> None:
    papers = [
        paper("openalex", "A Study Of Things", year=2020),
        paper("crossref", "A study of things", year=2022),
    ]
    assert len(merge_papers(papers, PRECEDENCE)) == 2


def test_unknown_year_still_matches_on_title() -> None:
    papers = [
        paper("openalex", "A Study Of Things", year=2020),
        paper("crossref", "A study of things"),
    ]
    assert len(merge_papers(papers, PRECEDENCE)) == 1


def test_distinct_works_pass_through_untouched() -> None:
    papers = [
        paper("openalex", "First Work", doi="10.1/a"),
        paper("crossref", "Second Work", doi="10.1/b"),
        paper("core", "Third Work"),
    ]
    merged = merge_papers(papers, PRECEDENCE)
    assert [p.title for p in merged] == ["First Work", "Second Work", "Third Work"]
    # Nothing merged, so nothing is annotated as corroborated.
    assert all("also_in" not in p.extra for p in merged)


def test_empty_input() -> None:
    assert merge_papers([], PRECEDENCE) == []


# ---------------------------------------------------------------------------
# Field-level merging
# ---------------------------------------------------------------------------


def test_precedence_decides_scalar_conflicts() -> None:
    papers = [
        paper("crossref", doi="10.1/a", venue="Crossref Venue", url="https://crossref"),
        paper("openalex", doi="10.1/a", venue="OpenAlex Venue", url="https://openalex"),
    ]
    merged = merge_papers(papers, PRECEDENCE)[0]
    assert merged.venue == "OpenAlex Venue"
    assert merged.url == "https://openalex"
    assert merged.source == "openalex"


def test_lower_precedence_fills_fields_the_winner_lacks() -> None:
    papers = [
        paper("openalex", doi="10.1/a", venue=None, pdf_url=None),
        paper("core", doi="10.1/a", venue="NeurIPS", pdf_url="https://core/x.pdf"),
    ]
    merged = merge_papers(papers, PRECEDENCE)[0]
    assert merged.venue == "NeurIPS"
    assert merged.pdf_url == "https://core/x.pdf"


def test_citation_count_takes_the_maximum() -> None:
    """Coverage differs between indexes; the truth does not."""
    papers = [
        paper("openalex", doi="10.1/a", citation_count=120),
        paper("crossref", doi="10.1/a", citation_count=98000),
        paper("core", doi="10.1/a", citation_count=None),
    ]
    assert merge_papers(papers, PRECEDENCE)[0].citation_count == 98000


def test_citation_count_stays_none_when_nobody_knows() -> None:
    papers = [paper("openalex", doi="10.1/a"), paper("crossref", doi="10.1/a")]
    assert merge_papers(papers, PRECEDENCE)[0].citation_count is None


def test_longest_author_list_wins_regardless_of_precedence() -> None:
    papers = [
        paper("openalex", doi="10.1/a", authors=("Vaswani, A.",)),
        paper("crossref", doi="10.1/a", authors=("Vaswani, A.", "Shazeer, N.", "Parmar, N.")),
    ]
    merged = merge_papers(papers, PRECEDENCE)[0]
    assert merged.authors == ("Vaswani, A.", "Shazeer, N.", "Parmar, N.")


def test_author_tie_goes_to_precedence() -> None:
    papers = [
        paper("openalex", doi="10.1/a", authors=("A. One", "B. Two")),
        paper("crossref", doi="10.1/a", authors=("One, A.", "Two, B.")),
    ]
    assert merge_papers(papers, PRECEDENCE)[0].authors == ("A. One", "B. Two")


def test_longest_nonempty_abstract_wins() -> None:
    """Crossref returns empty or partial abstracts for whole publishers."""
    papers = [
        paper("openalex", doi="10.1/a", abstract=""),
        paper("crossref", doi="10.1/a", abstract="Short."),
        paper("core", doi="10.1/a", abstract="A considerably longer abstract body."),
    ]
    merged = merge_papers(papers, PRECEDENCE)[0]
    assert merged.abstract == "A considerably longer abstract body."


def test_abstract_stays_none_when_all_are_empty() -> None:
    papers = [
        paper("openalex", doi="10.1/a", abstract=None),
        paper("crossref", doi="10.1/a", abstract=""),
    ]
    assert merge_papers(papers, PRECEDENCE)[0].abstract is None


def test_year_comes_from_the_preferred_provider_that_has_one() -> None:
    papers = [
        paper("openalex", doi="10.1/a", year=None),
        paper("crossref", doi="10.1/a", year=2017),
    ]
    assert merge_papers(papers, PRECEDENCE)[0].year == 2017


def test_also_in_records_every_contributing_source() -> None:
    papers = [
        paper("crossref", doi="10.1/a"),
        paper("core", doi="10.1/a"),
        paper("openalex", doi="10.1/a"),
    ]
    merged = merge_papers(papers, PRECEDENCE)[0]
    assert merged.extra["also_in"] == "openalex,crossref,core"


def test_also_in_dedupes_repeat_hits_from_one_provider() -> None:
    papers = [
        paper("openalex", doi="10.1/a"),
        paper("openalex", doi="10.1/a"),
    ]
    merged = merge_papers(papers, PRECEDENCE)
    assert len(merged) == 1
    assert "also_in" not in merged[0].extra


def test_extra_keys_survive_the_merge_with_precedence_winning_conflicts() -> None:
    papers = [
        paper("openalex", doi="10.1/a", extra={"oa_status": "gold"}),
        paper("crossref", doi="10.1/a", extra={"oa_status": "closed", "publisher": "ACM"}),
    ]
    merged = merge_papers(papers, PRECEDENCE)[0]
    assert merged.extra["oa_status"] == "gold"
    assert merged.extra["publisher"] == "ACM"


def test_source_paper_is_not_mutated() -> None:
    original = paper("crossref", doi="10.1/a", extra={"publisher": "ACM"})
    merge_papers([original, paper("openalex", doi="10.1/a")], PRECEDENCE)
    assert original.extra == {"publisher": "ACM"}


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_output_is_ordered_by_precedence_then_first_seen() -> None:
    papers = [
        paper("core", "C Work", doi="10.1/c"),
        paper("crossref", "B Work", doi="10.1/b"),
        paper("openalex", "A Work", doi="10.1/a"),
        paper("openalex", "D Work", doi="10.1/d"),
    ]
    merged = merge_papers(papers, PRECEDENCE)
    assert [p.title for p in merged] == ["A Work", "D Work", "B Work", "C Work"]


def test_unknown_providers_sort_last_in_first_seen_order() -> None:
    papers = [
        paper("mystery", "M Work", doi="10.1/m"),
        paper("other", "O Work", doi="10.1/o"),
        paper("openalex", "A Work", doi="10.1/a"),
    ]
    merged = merge_papers(papers, PRECEDENCE)
    assert [p.title for p in merged] == ["A Work", "M Work", "O Work"]


def test_merge_is_deterministic_across_input_orderings() -> None:
    a = paper("openalex", "Shared Work", doi="10.1/a", citation_count=10)
    b = paper("crossref", "Shared Work", doi="10.1/a", citation_count=20)
    other = paper("core", "Other Work", doi="10.1/z")
    first = merge_papers([a, b, other], PRECEDENCE)
    second = merge_papers([other, b, a], PRECEDENCE)
    assert [p.to_dict() for p in first] == [p.to_dict() for p in second]
