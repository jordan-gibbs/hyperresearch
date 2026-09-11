"""Academic and specialist discovery — finding records, not enriching them."""

from hyperresearch.scholar.base import (
    Paper,
    ProviderError,
    SearchProvider,
    normalize_doi,
    title_key,
)

__all__ = ["Paper", "ProviderError", "SearchProvider", "normalize_doi", "title_key"]
