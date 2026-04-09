"""Note and frontmatter models."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


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


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug. Preserves underscores."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    result = text.strip("-")
    if not result:
        # Fallback for titles with only special/non-ASCII characters
        import hashlib
        result = "note-" + hashlib.sha256(text.encode()).hexdigest()[:8]
    return result


class NoteMeta(BaseModel):
    """YAML frontmatter schema for a hyperresearch note."""

    title: str
    id: str = ""
    tags: list[str] = Field(default_factory=list)
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated: datetime | None = None
    source: str | None = None
    status: NoteStatus = NoteStatus.DRAFT
    type: NoteType = NoteType.NOTE
    aliases: list[str] = Field(default_factory=list)
    parent: str | None = None
    confidence: float | None = None
    superseded_by: str | None = None    # Note ID that replaces this one
    deprecated: bool = False             # Explicitly marked as outdated
    reviewed: datetime | None = None     # Last time a human verified accuracy
    expires: datetime | None = None      # Auto-stale after this date
    llm_compiled: bool = False
    llm_model: str | None = None
    compile_source: str | None = None
    summary: str | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def lowercase_tags(cls, v: list[str]) -> list[str]:
        return [t.lower().strip() for t in v]

    @field_validator("id", mode="before")
    @classmethod
    def ensure_slug(cls, v: str) -> str:
        if v:
            return slugify(v)
        return v

    model_config = {"use_enum_values": True}


class Note(BaseModel):
    """A full note: metadata + body + disk info."""

    meta: NoteMeta
    body: str
    path: str  # Relative path from vault root
    content_hash: str = ""
    word_count: int = 0
    outgoing_links: list[str] = Field(default_factory=list)
