"""Search result models."""

from __future__ import annotations

from pydantic import BaseModel


class SearchResult(BaseModel):
    id: str
    title: str
    path: str
    status: str
    tags: list[str]
    created: str
    updated: str | None
    score: float
    snippet: str = ""


class SearchResponse(BaseModel):
    query: str
    filters: dict
    total: int
    results: list[SearchResult]
