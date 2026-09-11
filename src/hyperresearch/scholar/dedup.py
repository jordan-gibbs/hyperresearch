"""Cross-provider deduplication.

Every provider in this package answers the same query from its own index, so
the same work comes back several times with different metadata completeness:
OpenAlex has the citation count, Crossref has the DOI and the venue, CORE has
the PDF, and one of them has an abstract. Concatenating those lists produces a
corpus with triplicate entries, and every downstream count in this project —
source totals, citation density, ranking percentiles — is then wrong in a way
that looks plausible.

`merge_papers` collapses them into one record per work, taking the best
available value for each field rather than picking a single winning provider.
Which provider "best" means is the `precedence` argument: registry order, so
the broadest, best-maintained metadata source wins field-level ties.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from hyperresearch.scholar.base import Paper, normalize_doi, title_key

__all__ = ["merge_papers"]

# Providers disagree systematically about online-first versus print year for
# the same article, so an exact year match loses real duplicates. One year of
# slack recovers them; two would start merging conference/journal versions of
# genuinely distinct works that share a title.
_YEAR_SLACK = 1


# eq=False so cluster membership checks are identity, not a field-by-field
# comparison that would treat two freshly-created empty clusters as the same.
@dataclass(eq=False)
class _Cluster:
    """One work, plus every record that turned out to be the same work."""

    first_seen: int
    members: list[Paper] = field(default_factory=list)
    doi: str | None = None
    title_keys: set[str] = field(default_factory=set)
    years: set[int] = field(default_factory=set)

    def add(self, paper: Paper, doi: str | None, key: str) -> None:
        self.members.append(paper)
        if doi and not self.doi:
            self.doi = doi
        if key:
            self.title_keys.add(key)
        if paper.year is not None:
            self.years.add(paper.year)

    def doi_compatible(self, doi: str | None) -> bool:
        """Two records carrying different DOIs are different works, full stop.

        This is what keeps an aggressive title fingerprint from merging an
        erratum, a preprint with a DOI of its own, or two same-titled papers.
        """
        return not (doi and self.doi and doi != self.doi)

    def year_compatible(self, year: int | None) -> bool:
        # An unknown year cannot disprove a title match, and providers omit
        # the year often enough that treating None as a mismatch would leave
        # duplicates in the corpus.
        if year is None or not self.years:
            return True
        return any(abs(year - known) <= _YEAR_SLACK for known in self.years)


def _rank(source: str, precedence: list[str]) -> int:
    try:
        return precedence.index(source)
    except ValueError:
        # Unknown providers sort behind every known one, in first-seen order.
        return len(precedence)


def _longest(values: list[str | None]) -> str | None:
    """Longest non-empty string, ties broken by precedence order of `values`."""
    best: str | None = None
    for value in values:
        if not value:
            continue
        if best is None or len(value) > len(best):
            best = value
    return best


def _first(values: list[str | None]) -> str | None:
    for value in values:
        if value is not None:
            return value
    return None


def _merge_cluster(cluster: _Cluster, precedence: list[str]) -> Paper:
    """Collapse one cluster to a single record, field by field."""
    ordered = sorted(
        enumerate(cluster.members),
        key=lambda pair: (_rank(pair[1].source, precedence), pair[0]),
    )
    members = [paper for _, paper in ordered]
    primary = members[0]
    if len(members) == 1:
        return primary

    # extra: earlier-precedence keys win, but a key only one provider carries
    # survives — the point of merging is to lose nothing recoverable.
    extra: dict[str, str] = {}
    for paper in reversed(members):
        extra.update(paper.extra)

    sources: list[str] = []
    for paper in members:
        if paper.source and paper.source not in sources:
            sources.append(paper.source)
    if len(sources) > 1:
        extra["also_in"] = ",".join(sources)

    counts = [p.citation_count for p in members if p.citation_count is not None]
    authors = max(members, key=lambda p: len(p.authors)).authors
    # max() is not stable the way we need it here: it returns the FIRST
    # maximum, and `members` is already in precedence order, so a tie goes to
    # the preferred provider. That is the intended rule.

    return replace(
        primary,
        url=_first([p.url for p in members]),
        doi=_first([p.doi for p in members]),
        year=next((p.year for p in members if p.year is not None), None),
        authors=authors,
        venue=_first([p.venue for p in members]),
        # Coverage differs between providers rather than the truth differing,
        # so the highest count is the least-wrong one.
        citation_count=max(counts) if counts else None,
        abstract=_longest([p.abstract for p in members]),
        pdf_url=_first([p.pdf_url for p in members]),
        identifier=_first([p.identifier for p in members]),
        extra=extra,
    )


def merge_papers(papers: list[Paper], precedence: list[str]) -> list[Paper]:
    """Collapse duplicate records across providers into one record per work.

    Matching is DOI-first and title+year second:

    1. Normalized DOI, authoritative when both sides have one — equal DOIs
       merge, different DOIs never merge whatever the titles say.
    2. `title_key` plus year proximity (+/-1) when either side lacks a DOI.

    `precedence` is a list of provider slugs, earliest preferred. It decides
    field-level conflicts and, with first-seen order, the order of the result,
    so repeated runs over the same corpus produce byte-identical reports.
    """
    clusters: list[_Cluster] = []
    by_doi: dict[str, _Cluster] = {}
    by_title: dict[str, list[_Cluster]] = {}

    for index, paper in enumerate(papers):
        doi = normalize_doi(paper.doi)
        key = title_key(paper.title)

        target: _Cluster | None = None
        if doi is not None:
            target = by_doi.get(doi)
        if target is None and key:
            for candidate in by_title.get(key, []):
                if candidate.doi_compatible(doi) and candidate.year_compatible(paper.year):
                    target = candidate
                    break
        if target is None:
            target = _Cluster(first_seen=index)
            clusters.append(target)

        had_doi = target.doi
        target.add(paper, doi, key)
        if target.doi and target.doi != had_doi:
            by_doi.setdefault(target.doi, target)
        if key and target not in by_title.setdefault(key, []):
            by_title[key].append(target)

    merged = [(cluster, _merge_cluster(cluster, precedence)) for cluster in clusters]
    merged.sort(key=lambda pair: (_rank(pair[1].source, precedence), pair[0].first_seen))
    return [paper for _, paper in merged]
