"""Content similarity — shingle-based Jaccard for dedup and create-time checks."""

from __future__ import annotations


def shingle(text: str, n: int = 3) -> set[str]:
    """Extract word-level n-grams (shingles) from text."""
    words = text.lower().split()
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0
