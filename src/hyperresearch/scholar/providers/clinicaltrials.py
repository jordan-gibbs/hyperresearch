"""ClinicalTrials.gov — the U.S. public registry of clinical studies.

A corpus about a drug, a device or any other intervention legitimately cites
the trial itself and not only the papers written about it. The registration
carries the status, the phase, the sponsor and the enrollment, and it exists
from the day the study starts — often years before the first publication and
sometimes instead of one, since null results go unpublished far more often
than they go unregistered. These records are `work_type="trial"`.

API v2 (`/api/v2/studies`) is keyless and returns JSON. Two upstream quirks
shape the parsing below:

* Everything substantive is nested two levels down, under `protocolSection`,
  in modules that are individually OPTIONAL. A withdrawn or barely-filled
  registration arrives with no `descriptionModule` and no `designModule` at
  all, and even `protocolSection` itself is not guaranteed on every record
  shape the API can emit. So every accessor here tolerates an absent module
  instead of assuming the shape of the fullest record we happened to inspect.
* The NCT id is not a URL, and the API path is not citable. The canonical
  human-readable page is `https://clinicaltrials.gov/study/<nctId>`, which is
  what a reader following a citation needs.

Endpoint and response shape confirmed against the live API on 2026-09-11.
"""

from __future__ import annotations

import sqlite3
from typing import Any, ClassVar
from urllib.parse import quote

from hyperresearch.scholar.base import (
    Paper,
    SearchProvider,
    clamp_limit,
    coerce_year,
    fetch_json,
)

_BASE = "https://clinicaltrials.gov/api/v2/studies"

# The API's own ceiling for pageSize. Asking for more is a 400, not a clamp.
_MAX_PAGE_SIZE = 1000

# Trials list dozens of conditions apiece. `extra` is display metadata, not an
# index, so keep it to the ones a human scanning results would actually read.
_MAX_CONDITIONS = 6


def _module(section: Any, name: str) -> dict[str, Any]:
    """One `protocolSection` module as a dict — `{}` when absent or malformed.

    Collapsing "missing", "null" and "not a dict" into one empty-dict case is
    what keeps a sparse registration from raising three subscripts later.
    """
    if not isinstance(section, dict):
        return {}
    value = section.get(name)
    return value if isinstance(value, dict) else {}


def _text(mapping: dict[str, Any], key: str) -> str | None:
    """A non-empty trimmed string field, else None."""
    value = mapping.get(key)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _strings(mapping: dict[str, Any], key: str) -> list[str]:
    """A list-of-strings field, filtered to the non-empty entries."""
    value = mapping.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


class ClinicalTrialsProvider(SearchProvider):
    """Interventional and observational study registrations."""

    slug: ClassVar[str] = "clinicaltrials"
    label: ClassVar[str] = "ClinicalTrials.gov"
    covers: ClassVar[str] = (
        "Registered clinical studies — status, phase, sponsor, enrollment, "
        "conditions. Includes trials that never produced a paper. No key."
    )
    needs_key: ClassVar[bool] = False
    key_env: ClassVar[tuple[str, ...]] = ()

    def search(
        self,
        conn: sqlite3.Connection | None,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
    ) -> list[Paper]:
        term = query.strip()
        if not term:
            return []
        ceiling = clamp_limit(limit, _MAX_PAGE_SIZE)
        # countTotal costs the upstream a second aggregation and we never show
        # a total, so leave it off.
        url = f"{_BASE}?format=json&countTotal=false&query.term={quote(term)}&pageSize={ceiling}"
        payload = fetch_json(conn, url, fresh=fresh)
        if not isinstance(payload, dict):
            return []
        studies = payload.get("studies")
        if not isinstance(studies, list):
            return []

        papers: list[Paper] = []
        for study in studies:
            paper = self._to_paper(study)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= ceiling:
                break
        return papers

    def _to_paper(self, study: Any) -> Paper | None:
        """One study record, or None when it carries nothing citable."""
        if not isinstance(study, dict):
            return None
        section = study.get("protocolSection")
        identification = _module(section, "identificationModule")
        nct_id = _text(identification, "nctId")
        # briefTitle is the registry's display title; officialTitle is the
        # protocol title, which is longer and present on some records where
        # briefTitle is not.
        title = _text(identification, "briefTitle") or _text(identification, "officialTitle")
        if not nct_id or not title:
            return None

        status = _module(section, "statusModule")
        design = _module(section, "designModule")
        sponsors = _module(section, "sponsorCollaboratorsModule")
        description = _module(section, "descriptionModule")
        conditions = _module(section, "conditionsModule")

        start_struct = status.get("startDateStruct")
        start_date = _text(start_struct, "date") if isinstance(start_struct, dict) else None

        lead_struct = sponsors.get("leadSponsor")
        lead_sponsor = _text(lead_struct, "name") if isinstance(lead_struct, dict) else None

        extra: dict[str, str] = {"nct_id": nct_id}
        overall_status = _text(status, "overallStatus")
        if overall_status:
            extra["status"] = overall_status
        # Phase is a list because a single study can span two, as in the very
        # common "Phase 1/Phase 2" dose-escalation-then-expansion design.
        phases = _strings(design, "phases")
        if phases:
            extra["phase"] = "/".join(phases)
        study_type = _text(design, "studyType")
        if study_type:
            extra["study_type"] = study_type
        enrollment = design.get("enrollmentInfo")
        if isinstance(enrollment, dict) and isinstance(enrollment.get("count"), int):
            extra["enrollment"] = str(enrollment["count"])
        condition_names = _strings(conditions, "conditions")[:_MAX_CONDITIONS]
        if condition_names:
            extra["conditions"] = "; ".join(condition_names)
        if start_date:
            extra["start_date"] = start_date
        if lead_sponsor:
            extra["lead_sponsor"] = lead_sponsor

        return Paper(
            title=title,
            source=self.slug,
            url=f"https://clinicaltrials.gov/study/{nct_id}",
            # A trial's "year" is the year it started. Registration and first
            # posting dates are both later and both less useful for sorting.
            year=coerce_year(start_date),
            # A trial has sponsors, not authors. The sponsor is the closest
            # thing to a publisher of record, so it goes in `venue`.
            venue=lead_sponsor,
            abstract=_text(description, "briefSummary"),
            work_type="trial",
            identifier=nct_id,
            extra=extra,
        )
