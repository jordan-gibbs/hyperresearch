"""Note and frontmatter models."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr, field_validator


class NoteStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    EVERGREEN = "evergreen"
    STALE = "stale"
    DEPRECATED = "deprecated"
    ARCHIVE = "archive"


class NoteType(StrEnum):
    NOTE = "note"
    RAW = "raw"
    INDEX = "index"
    MOC = "moc"
    INTERIM = "interim"  # hyperresearch depth-investigator output (Layer 3)
    SOURCE_ANALYSIS = "source-analysis"  # deep single-source analytical digest


class Tier(StrEnum):
    """Epistemic role of a source — how it functions as evidence."""
    GROUND_TRUTH = "ground_truth"
    INSTITUTIONAL = "institutional"
    PRACTITIONER = "practitioner"
    COMMENTARY = "commentary"
    UNKNOWN = "unknown"


class ContentType(StrEnum):
    """Artifact kind — what the note physically is."""
    PAPER = "paper"
    DOCS = "docs"
    ARTICLE = "article"
    BLOG = "blog"
    FORUM = "forum"
    DATASET = "dataset"
    POLICY = "policy"
    CODE = "code"
    BOOK = "book"
    TRANSCRIPT = "transcript"
    REVIEW = "review"
    UNKNOWN = "unknown"


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug. Preserves underscores.

    Unicode-aware: CJK, Cyrillic, Arabic, and accented Latin characters are kept.
    Stripping them (the old `flags=re.ASCII` behaviour) collapsed every non-Latin
    title to whatever ASCII it happened to contain — so `バックライト - Wikipedia`
    became `wikipedia`, and a vault of Japanese sources degenerated into
    `wikipedia`, `wikipedia-2`, `wikipedia-3`, with meaningless [[wikilink]] ids.
    """
    # NFC-normalise so visually identical titles always yield the same slug.
    text = unicodedata.normalize("NFC", text).lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)  # Unicode-aware \w — no re.ASCII
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    result = text.strip("-")
    if not result:
        # Fallback for titles with only punctuation/symbols
        import hashlib
        result = "note-" + hashlib.sha256(text.encode()).hexdigest()[:8]
    # Cap length twice: characters (Windows MAX_PATH) and UTF-8 bytes, since most
    # filesystems limit a filename to 255 *bytes* and one CJK character costs 3.
    if len(result) > 80:
        result = result[:80]
    if len(result.encode("utf-8")) > 200:
        result = result.encode("utf-8")[:200].decode("utf-8", errors="ignore")
    return result.rstrip("-")


def _yaml_scalar_str(v: Any) -> Any:
    """Hand-written YAML reads `2024` as an int and `2024-01-01` as a date.

    A YAML boolean is left for validation to reject: `tags: [no, on]` read as
    'false' and 'true' would be written back over the user's tags.
    """
    if isinstance(v, int | float | date) and not isinstance(v, bool):
        return str(v)
    return v


class NoteMeta(BaseModel):
    """YAML frontmatter schema for a hyperresearch note."""

    title: str
    id: str = ""
    tags: list[str] = Field(default_factory=list)
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated: datetime | None = None
    source: str | None = None
    source_domain: str | None = None
    fetched_at: datetime | None = None
    fetch_provider: str | None = None
    status: NoteStatus = NoteStatus.DRAFT
    type: NoteType = NoteType.NOTE
    tier: Tier | None = None             # Epistemic role (ground_truth/institutional/practitioner/commentary)
    content_type: ContentType | None = None  # Artifact kind (paper/docs/article/blog/...)
    aliases: list[str] = Field(default_factory=list)
    parent: str | None = None
    deprecated: bool = False             # Explicitly marked as outdated
    reviewed: datetime | None = None     # Last time a human verified accuracy
    expires: datetime | None = None      # Auto-stale after this date
    summary: str | None = None
    raw_file: str | None = None          # Relative path to raw artifact (e.g. raw/<id>.pdf)
    # Source-ranking fields (frontmatter-mirrored; markdown stays truth).
    # Derived scores (authority/centrality/independence/quality) are DB-cache
    # only and deliberately NOT in frontmatter — they are recomputed.
    doi: str | None = None               # DOI or arXiv id (e.g. 10.1234/x, arXiv:2501.01234)
    utility_score: float | None = None   # Step-2 fetch-selection composite (0-18)
    citation_count: int | None = None    # External citation count (OpenAlex/S2)
    venue: str | None = None             # Publication venue, when known
    is_retracted: bool | None = None     # None = unchecked; set by `hpr sources score`
    # Open-access recovery (core/oa.py). When these are set, the note BODY came
    # from `oa_url`, NOT from `source` — `source` stays the URL that was asked
    # for, because the note is about the paper and the DOI is its identity.
    oa_url: str | None = None            # Where the body's bytes actually came from
    oa_source: str | None = None         # Resolver: unpaywall | europepmc | core
    oa_version: str | None = None        # publishedVersion | acceptedVersion | submittedVersion
    oa_license: str | None = None        # Licence reported by the resolver, when known
    # substituted = a thin page was replaced. rescued = the source could not be
    # read at all, so the ENTIRE note (title and authors included) is the
    # open-access copy and nothing in it came from `source`.
    oa_recovery_kind: str | None = None

    # Frontmatter keys this model does not define (authors, year, url, ...),
    # with their YAML values, and the order of every key in the file.
    # parse_frontmatter fills both and serialize_frontmatter writes the keys
    # back, so rewriting one field keeps the rest of the user's frontmatter.
    # Private, so a NoteMeta built from keyword arguments (write_note given a
    # fetch's scraped metadata) still drops unknown keys.
    _extra: dict[Any, Any] = PrivateAttr(default_factory=dict)
    _key_order: list[Any] = PrivateAttr(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def lowercase_tags(cls, v: Any) -> Any:
        # Obsidian-style `tags: research` is a comma list, not a string to
        # iterate character by character, and an empty `tags:` is no tags.
        if v is None:
            return []
        if isinstance(v, str):
            v = v.split(",")
        elif not isinstance(v, list | tuple | set):
            v = [v]
        tags = []
        for item in v:
            tag = _yaml_scalar_str(item)
            if isinstance(tag, str):
                tag = tag.lower().strip()
            # Empty entries are dropped. Any other non-string (a mapping, a
            # nested list) is left for pydantic to reject with a field-level
            # message.
            if tag is not None and tag != "":
                tags.append(tag)
        return tags

    @field_validator("id", mode="before")
    @classmethod
    def ensure_slug(cls, v: Any) -> Any:
        if v is None:
            return ""
        v = _yaml_scalar_str(v)
        if v and isinstance(v, str):
            return slugify(v)
        return v

    model_config = {"use_enum_values": True, "extra": "ignore"}


class Note(BaseModel):
    """A full note: metadata + body + disk info."""

    meta: NoteMeta
    body: str
    path: str  # Relative path from vault root
    # Set by read_note: whether the file opens with a frontmatter that did not
    # parse, and whether the frontmatter gave `meta.id` (otherwise the id is
    # the filename stem).
    frontmatter_broken: bool = False
    id_declared: bool = False
    content_hash: str = ""
    word_count: int = 0
    outgoing_links: list[str] = Field(default_factory=list)
