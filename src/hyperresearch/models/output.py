"""Envelope models for consistent CLI output."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Envelope(BaseModel):
    """Standard JSON output wrapper for all commands."""

    ok: bool = True
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    count: int | None = None
    vault: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def success(data: Any, count: int | None = None, vault: str | None = None) -> Envelope:
    return Envelope(ok=True, data=data, count=count, vault=vault)


def error(message: str, code: str = "ERROR", vault: str | None = None) -> Envelope:
    return Envelope(ok=False, error=message, error_code=code, vault=vault)
