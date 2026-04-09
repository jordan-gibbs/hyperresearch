"""Graph and link models."""

from __future__ import annotations

from pydantic import BaseModel


class LinkEntry(BaseModel):
    source_id: str
    target_ref: str
    target_id: str | None
    line_number: int | None
    context: str = ""


class BacklinkEntry(BaseModel):
    source_id: str
    source_title: str
    source_path: str
    line_number: int | None
    context: str = ""
