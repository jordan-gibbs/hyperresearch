"""Shared regex patterns for wiki-link parsing."""

from __future__ import annotations

import re

# Match [[target]] and [[target|display text]]
WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Code block patterns for stripping before link extraction
CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]+`")
