"""Provider registry.

Providers are listed here in the order a multi-source search should prefer
them when merging duplicates: earlier entries win field-level conflicts, so
the broadest, best-maintained metadata sources come first.

Imports are resolved lazily and individually. A provider module that fails to
import disables that one source instead of taking down `hpr scholar` — which
matters because several of these depend on upstream APIs whose client shape
we do not control.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hyperresearch.scholar.base import SearchProvider

# (module suffix, class name). Order is merge precedence, not search order.
_REGISTRY: tuple[tuple[str, str], ...] = (
    ("openalex", "OpenAlexProvider"),
    ("crossref", "CrossrefProvider"),
    ("core_oa", "CoreProvider"),
    ("repec", "RePEcProvider"),
    ("doab", "DoabProvider"),
    ("clinicaltrials", "ClinicalTrialsProvider"),
    ("edgar", "EdgarProvider"),
    ("fred", "FredProvider"),
)

# Sources that are academic literature, as opposed to the specialist verticals
# (trials, filings, economic series). `--scope papers` selects this set.
PAPER_SLUGS = frozenset({"openalex", "crossref", "core", "repec", "doab"})


def _load(module_suffix: str, class_name: str) -> SearchProvider | None:
    try:
        module = importlib.import_module(f"hyperresearch.scholar.providers.{module_suffix}")
    except ImportError:
        return None
    cls = getattr(module, class_name, None)
    if cls is None:
        return None
    try:
        instance = cls()
    except Exception:
        return None
    return instance  # type: ignore[no-any-return]


def all_providers() -> list[SearchProvider]:
    """Every provider whose module imports, available or not."""
    found: list[SearchProvider] = []
    for suffix, class_name in _REGISTRY:
        provider = _load(suffix, class_name)
        if provider is not None:
            found.append(provider)
    return found


def all_slugs() -> list[str]:
    return [p.slug for p in all_providers()]


def get_providers(
    slugs: list[str] | None = None,
    *,
    scope: str = "all",
    include_unavailable: bool = False,
) -> list[SearchProvider]:
    """Resolve a selection of providers.

    `slugs` None means "everything in scope". Providers missing a required key
    are dropped unless `include_unavailable`, so a user without a CORE key
    still gets results from everything else rather than an error.
    """
    providers = all_providers()
    if scope == "papers":
        providers = [p for p in providers if p.slug in PAPER_SLUGS]
    if slugs:
        wanted = {s.strip().lower() for s in slugs if s.strip()}
        providers = [p for p in providers if p.slug in wanted]
    if not include_unavailable:
        providers = [p for p in providers if p.available()]
    return providers


def unavailable_notes(scope: str = "all") -> list[str]:
    """Human-readable reasons for each provider we had to skip."""
    notes: list[str] = []
    for provider in get_providers(scope=scope, include_unavailable=True):
        reason = provider.unavailable_reason()
        if reason:
            notes.append(reason)
    return notes
