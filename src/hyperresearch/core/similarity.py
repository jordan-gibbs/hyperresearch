"""Content similarity — shingle-based Jaccard + MinHash/LSH for dedup."""

from __future__ import annotations

import hashlib
import struct
from collections import defaultdict

_MAX_HASH = (1 << 32) - 1


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


def minhash_signature(shingles: set[str], num_perm: int = 128) -> list[int]:
    """Compute a MinHash signature for a set of shingles.

    Uses SHA-256 with different salts as the hash family.
    """
    if not shingles:
        return [_MAX_HASH] * num_perm

    sig = [_MAX_HASH] * num_perm
    for s in shingles:
        s_bytes = s.encode("utf-8")
        for i in range(num_perm):
            h = struct.unpack("<I", hashlib.sha256(
                i.to_bytes(2, "little") + s_bytes
            ).digest()[:4])[0]
            if h < sig[i]:
                sig[i] = h
    return sig


def lsh_candidates(
    signatures: dict[str, list[int]],
    bands: int = 16,
) -> set[tuple[str, str]]:
    """Find candidate duplicate pairs using Locality-Sensitive Hashing.

    Divides each signature into `bands` bands. Items sharing a band bucket
    are candidate pairs.
    """
    if not signatures:
        return set()

    num_perm = len(next(iter(signatures.values())))
    rows_per_band = num_perm // bands

    candidates: set[tuple[str, str]] = set()
    for band_idx in range(bands):
        buckets: dict[int, list[str]] = defaultdict(list)
        start = band_idx * rows_per_band
        end = start + rows_per_band

        for doc_id, sig in signatures.items():
            band_hash = hash(tuple(sig[start:end]))
            buckets[band_hash].append(doc_id)

        for bucket_items in buckets.values():
            if len(bucket_items) > 1:
                for i in range(len(bucket_items)):
                    for j in range(i + 1, len(bucket_items)):
                        a, b = bucket_items[i], bucket_items[j]
                        candidates.add((min(a, b), max(a, b)))

    return candidates
