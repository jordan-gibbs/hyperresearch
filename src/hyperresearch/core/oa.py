"""Open-access full-text recovery — Unpaywall + Europe PMC.

A paywalled paper otherwise enters the vault as an abstract. `extract_doi`
already stamps `doi:` on every fetched note, the junk gate passes a publisher
landing page (an abstract is not junk), and downstream investigators then
reason over ~1-3k characters while the report cites the work as though the
paper had been read.

This module closes that gap. Given a DOI and a thin fetch result, it asks two
free APIs whether a legal open-access copy exists and, if so, refetches from
there:

1. **Unpaywall** (`api.unpaywall.org`) — broad coverage, but their terms want a
   real contact address, so it is SKIPPED unless `[scholar] contact_email` is
   set. Shipping one shared placeholder across every install is how that
   placeholder gets rate-limited for everybody.
2. **Europe PMC** (`www.ebi.ac.uk`) — no key, no email, biomedical only.

So the feature degrades cleanly: with no configuration at all it still recovers
biomedical literature; adding an email widens it to everything Unpaywall
indexes.

INVARIANTS
----------
* **Recovery can never fail a fetch.** Every error path returns the original
  result untouched, because the abstract you already have beats no note at all.
* **Recovery never shrinks a note.** If the recovered copy extracts to less
  text than the landing page, the landing page wins.
* **The swap is always disclosed** — in the note body (a blockquote banner), in
  four `oa_*` frontmatter fields, and in the CLI/JSON output. A reader must
  never have to guess that the bytes came from somewhere other than `source:`.
* **Resolved URLs are attacker-influenceable** (they arrive inside a
  third-party API response) and are therefore gated by `check_oa_url` before
  anything fetches them.

All HTTP goes through `scholar._fetch_json`, so lookups land in the `api_cache`
table and re-running a vault is cheap and offline-friendly. Tests monkeypatch
`scholar._http_get_json`; no test here hits the network.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import quote, urlparse

_UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
_EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# Preference order when a work has several open-access copies. The version of
# record first, then the peer-reviewed-but-unformatted accepted manuscript,
# then the preprint. Unknown versions sort last but are still usable.
_VERSION_RANK = {
    "publishedVersion": 0,
    "acceptedVersion": 1,
    "submittedVersion": 2,
}

# Phrases that mark a paywall interstitial regardless of page length — some
# publisher pages are long with navigation chrome but carry no article text.
_PAYWALL_PHRASES = (
    "purchase pdf",
    "buy this article",
    "rent this article",
    "purchase access",
    "subscribe to access",
    "sign in to continue reading",
    "access through your institution",
    "get access to the full",
)


@dataclass(frozen=True)
class OALocation:
    """One open-access copy of a work.

    `kind` decides how the bytes get turned into note text:
      "pdf"  — download and run through pymupdf, the same path arXiv takes
      "jats" — Europe PMC's structured full-text XML, parsed here
      "page" — an ordinary landing page, fetched through the web provider
    """

    url: str
    resolver: str  # "unpaywall" | "europepmc"
    kind: str  # "pdf" | "jats" | "page"
    version: str | None = None  # publishedVersion | acceptedVersion | submittedVersion
    license: str | None = None
    host_type: str | None = None  # "publisher" | "repository" (Unpaywall only)

    @property
    def is_version_of_record(self) -> bool:
        return self.version == "publishedVersion"


# ---------------------------------------------------------------------------
# URL safety
# ---------------------------------------------------------------------------


def check_oa_url(url: str) -> tuple[bool, str]:
    """Gate a resolver-supplied URL before fetching it. Returns (ok, reason).

    The URL comes out of a third-party API response, so a poisoned DOI record
    can steer the fetcher at internal infrastructure. This is a deliberately
    narrow SSRF check: scheme, no credentials in the netloc, and every address
    the host resolves to must be publicly routable.

    NOTE: this duplicates the intent of `web.safe_http.check_url` (PR #53).
    When that lands, collapse this into a call to it — the version there does
    redirect revalidation too, which this one cannot.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "unparseable URL"

    if parsed.scheme not in ("http", "https"):
        return False, f"scheme {parsed.scheme!r} is not http(s)"
    if parsed.username or parsed.password:
        return False, "credentials embedded in URL"

    host = parsed.hostname
    if not host:
        return False, "no host"
    if "." not in host and not _is_ip_literal(host):
        # Bare names ("localhost", "metadata", internal short hostnames) never
        # legitimately serve a published paper.
        return False, f"non-public hostname {host!r}"

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return False, f"DNS resolution failed: {exc}"

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            return False, f"unparseable address {addr!r}"
        if not ip.is_global or ip.is_multicast:
            return False, f"host resolves to non-public address {ip}"

    return True, ""


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def needs_oa_recovery(result, settings) -> bool:
    """Is this fetch result thin enough to be worth an OA lookup?

    A real paper body runs 20-80k characters; an abstract landing page runs
    1-3k. The length test avoids maintaining a publisher-domain list, and the
    caller has already established that a DOI is present, which scopes this to
    scholarly material. A false positive costs one cached API call.
    """
    if not settings.oa_recovery:
        return False
    if getattr(result, "raw_content_type", None) == "application/pdf":
        return False  # already full text
    content = result.content or ""
    if len(content) < settings.oa_min_full_text_chars:
        return True
    # Scan the whole body, not a prefix: on a chrome-heavy publisher page the
    # "purchase this article" interstitial sits below thousands of characters
    # of navigation. A false positive here costs one cached API call, and the
    # never-shrink rule in `recover_full_text` catches the rest.
    lowered = content.lower()
    return any(phrase in lowered for phrase in _PAYWALL_PHRASES)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def iter_oa_candidates(
    conn,
    doi: str,
    ttl_days: int,
    *,
    email: str | None = None,
    prefer_published: bool = True,
    fresh: bool = False,
):
    """Yield candidate open-access copies of `doi`, best first.

    A generator rather than a single answer, because publishers 403 their own
    open-access PDFs often enough that giving up on the first failure loses
    papers that are sitting in a repository two candidates down. Europe PMC is
    resolved lazily, so the extra API call only happens when Unpaywall's copies
    have all been exhausted.

    arXiv identifiers are declined outright: neither API resolves them, and an
    arXiv paper was already reachable as a PDF at fetch time.
    """
    if not doi or doi.lower().startswith("arxiv:"):
        return

    if email:
        yield from _unpaywall_candidates(conn, doi, ttl_days, email, prefer_published, fresh)

    epmc = _resolve_europepmc(conn, doi, ttl_days, fresh)
    if epmc is not None:
        yield epmc


def resolve_oa(
    conn,
    doi: str,
    ttl_days: int,
    *,
    email: str | None = None,
    prefer_published: bool = True,
    fresh: bool = False,
) -> OALocation | None:
    """The single best open-access copy of `doi`, or None."""
    for loc in iter_oa_candidates(
        conn, doi, ttl_days, email=email, prefer_published=prefer_published, fresh=fresh
    ):
        return loc
    return None


def _unpaywall_candidates(
    conn, doi: str, ttl_days: int, email: str, prefer_published: bool, fresh: bool
):
    from hyperresearch.core.scholar import _fetch_json

    url = f"{_UNPAYWALL_BASE}/{quote(doi, safe='')}?email={quote(email, safe='')}"
    data = _fetch_json(conn, url, ttl_days, fresh)
    if not data or not data.get("is_oa"):
        return

    # best_oa_location goes first so it wins ties under a stable sort.
    locations: list[dict] = []
    best = data.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    for loc in data.get("oa_locations") or []:
        if isinstance(loc, dict) and loc not in locations:
            locations.append(loc)

    def sort_key(loc: dict) -> tuple[int, int]:
        has_pdf = 0 if loc.get("url_for_pdf") else 1
        rank = _VERSION_RANK.get(loc.get("version") or "", 3) if prefer_published else 0
        return (has_pdf, rank)

    ordered = sorted(locations, key=sort_key)

    def build(loc: dict, target: str, kind: str) -> OALocation:
        return OALocation(
            url=target,
            resolver="unpaywall",
            kind=kind,
            version=loc.get("version") or None,
            license=loc.get("license") or None,
            host_type=loc.get("host_type") or None,
        )

    seen: set[str] = set()
    # Every PDF first, then the landing pages as fallbacks — a publisher that
    # blocks its PDF endpoint will often still serve the HTML article.
    for want_pdf in (True, False):
        for loc in ordered:
            target = loc.get("url_for_pdf") if want_pdf else loc.get("url")
            if not target or target in seen:
                continue
            seen.add(target)
            yield build(loc, target, "pdf" if want_pdf else "page")


def _resolve_europepmc(conn, doi: str, ttl_days: int, fresh: bool) -> OALocation | None:
    from hyperresearch.core.scholar import _fetch_json

    query = quote(f'DOI:"{doi}"', safe="")
    url = f"{_EPMC_BASE}/search?query={query}&format=json&resultType=core&pageSize=1"
    data = _fetch_json(conn, url, ttl_days, fresh)
    if not data:
        return None

    results = ((data.get("resultList") or {}).get("result")) or []
    if not results:
        return None
    rec = results[0]
    if rec.get("isOpenAccess") != "Y":
        return None
    pmcid = rec.get("pmcid")
    if not pmcid:
        return None

    # NOT `/fullTextPDF` — that endpoint 404s. `/fullTextXML` is the documented
    # REST route and returns JATS, which parses better than a two-column PDF
    # anyway: real section boundaries, no header bleed, no column interleaving.
    return OALocation(
        url=f"{_EPMC_BASE}/{quote(pmcid, safe='')}/fullTextXML",
        resolver="europepmc",
        kind="jats",
        version="publishedVersion",
        license=rec.get("license") or None,
        host_type="repository",
    )


# ---------------------------------------------------------------------------
# JATS full text
# ---------------------------------------------------------------------------

# Inline markup that should vanish into the surrounding sentence rather than
# contribute text of its own (cross-references, citation markers, labels).
_JATS_DROP = frozenset({"xref", "label", "table-wrap-foot", "fn", "graphic", "media"})


def _http_get_text(url: str) -> str | None:
    """Raw HTTP GET returning body text, or None on any failure.

    Isolated so tests can monkeypatch it, mirroring `scholar._http_get_json`.
    Deliberately NOT routed through `api_cache`: that table is for small JSON
    metadata, and the note itself is the cache for full text.
    """
    import httpx

    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=60,
            headers={"User-Agent": "hyperresearch (mailto:research@example.com)"},
        )
        if resp.status_code != 200:
            return None
        return resp.text
    except Exception:
        return None


def _jats_block_text(elem) -> str:
    """Flatten one block element to a single line of prose.

    Dropped elements lose their subtree but KEEP their tail: in
    `<p>Widgets matter <xref>[1]</xref> a great deal.</p>` the words "a great
    deal." are the xref's tail and belong to the paragraph, not the citation
    marker. Discarding them would silently truncate a sentence after every
    reference.
    """

    def walk(node) -> list[str]:
        parts: list[str] = []
        if node.text:
            parts.append(node.text)
        for child in node:
            if child.tag not in _JATS_DROP:
                parts.extend(walk(child))
            if child.tail:
                parts.append(child.tail)
        return parts

    return " ".join("".join(walk(elem)).split())


def jats_to_markdown(xml_text: str) -> str | None:
    """Convert Europe PMC JATS full text to markdown. None if unparseable.

    Keeps the title, the abstract, and the article body with its section
    hierarchy. Drops back matter (reference lists, competing-interest
    statements) — the body is what gets read and cited, and a flattened
    reference list is mostly noise in a note.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    out: list[str] = []

    title_el = root.find(".//front//article-title")
    if title_el is not None:
        title = _jats_block_text(title_el)
        if title:
            out.append(f"# {title}\n")

    abstract = root.find(".//front//abstract")
    if abstract is not None:
        out.append("## Abstract\n")
        for para in abstract.iter("p"):
            text = _jats_block_text(para)
            if text:
                out.append(text + "\n")

    body = root.find("body")
    if body is None:
        return "\n".join(out).strip() or None

    def walk(node, depth: int) -> None:
        for child in node:
            if child.tag == "sec":
                heading = child.find("title")
                if heading is not None:
                    text = _jats_block_text(heading)
                    if text:
                        out.append(f"{'#' * min(depth, 6)} {text}\n")
                walk(child, depth + 1)
            elif child.tag in ("p", "disp-quote"):
                text = _jats_block_text(child)
                if text:
                    out.append(text + "\n")
            elif child.tag in ("fig", "table-wrap"):
                caption = child.find("caption")
                if caption is not None:
                    text = _jats_block_text(caption)
                    if text:
                        out.append(f"*{text}*\n")
            elif child.tag == "list":
                for item in child.iter("list-item"):
                    text = _jats_block_text(item)
                    if text:
                        out.append(f"- {text}")
                out.append("")

    walk(body, 2)
    return "\n".join(out).strip() or None


# ---------------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------------

_VERSION_PROSE = {
    "publishedVersion": "the published version of record",
    "acceptedVersion": (
        "the accepted manuscript — peer-reviewed but not publisher-formatted, "
        "so pagination and final wording may differ from the version of record"
    ),
    "submittedVersion": (
        "the submitted preprint — NOT peer reviewed, and it may differ "
        "substantially from the published paper"
    ),
}


def recovery_notice(loc: OALocation, original_url: str, original_chars: int) -> str:
    """The banner prepended to a recovered note body.

    Loud on purpose. Anyone reading this note — human or agent — has to be able
    to see at a glance that the text below did not come from `source:`, and
    which version of the paper they are actually reading.
    """
    what = _VERSION_PROSE.get(
        loc.version or "", "an open-access copy of unrecorded version"
    )
    lines = [
        "> [!] **Open-access full text substituted.**",
        f"> The body below is **{what}**, retrieved from"
        f" <{loc.url}> via {loc.resolver}.",
        f"> It is NOT the content of {original_url}, which returned only"
        f" {original_chars:,} characters (an abstract or paywall page).",
    ]
    if loc.license:
        lines.append(f"> Licence reported by {loc.resolver}: `{loc.license}`.")
    if loc.version != "publishedVersion":
        # Fires for unknown versions too. Not knowing which version you are
        # reading is a reason to check a quotation, not a reason to skip the
        # warning.
        lines.append(
            "> **Quote this source with care** — check any direct quotation"
            " against the version of record before it reaches a report."
        )
    return "\n".join(lines) + "\n"


def oa_frontmatter(loc: OALocation) -> dict:
    """The `oa_*` frontmatter fields recording a recovery."""
    meta = {"oa_url": loc.url, "oa_source": loc.resolver}
    if loc.version:
        meta["oa_version"] = loc.version
    if loc.license:
        meta["oa_license"] = loc.license
    return meta


# ---------------------------------------------------------------------------
# Orchestration — shared by `fetch` and `fetch batch`
# ---------------------------------------------------------------------------


def _fetch_jats(url: str, fallback_title: str | None):
    """Fetch Europe PMC JATS and wrap it as a WebResult, or None."""
    from hyperresearch.web.base import WebResult

    xml_text = _http_get_text(url)
    if not xml_text:
        return None
    markdown = jats_to_markdown(xml_text)
    if not markdown:
        return None

    title = fallback_title
    first = markdown.splitlines()[0]
    if first.startswith("# "):
        title = first[2:].strip() or fallback_title
    return WebResult(url=url, title=title or "Untitled", content=markdown)


def recover_full_text(vault, prov, url: str, doi: str | None, result):
    """Try to replace a thin result with an open-access full text.

    Returns `(result, location)`. `location` is None when nothing was swapped,
    in which case `result` is returned untouched. Never raises — see the
    module docstring's invariants.
    """
    settings = getattr(vault.config, "scholar", None)
    if settings is None or not doi or not needs_oa_recovery(result, settings):
        return result, None

    import logging

    log = logging.getLogger(__name__)

    try:
        candidates = list(
            iter_oa_candidates(
                vault.db,
                doi,
                vault.config.ranking.api_cache_ttl_days,
                email=settings.contact_email or None,
                prefer_published=settings.oa_prefer_published,
            )
        )
    except Exception:
        return result, None

    attempts = 0
    for loc in candidates:
        if attempts >= settings.oa_max_attempts:
            log.debug("Open-access attempt cap reached for %s", doi)
            break

        ok, reason = check_oa_url(loc.url)
        if not ok:
            log.warning(
                "Refused open-access URL %s from %s: %s", loc.url, loc.resolver, reason
            )
            continue

        attempts += 1
        try:
            if loc.kind == "pdf":
                from hyperresearch.web.crawl4ai_provider import _fetch_pdf

                recovered = _fetch_pdf(loc.url, vault.config.fetch)
            elif loc.kind == "jats":
                recovered = _fetch_jats(loc.url, result.title)
            elif prov is not None:
                recovered = prov.fetch(loc.url)
            else:
                continue
        except Exception:
            continue

        if recovered is None:
            continue
        if recovered.looks_like_junk(vault.config.junk):
            continue

        # Two bars, and a candidate has to clear both. Never shrink a note: a
        # badly-extracted PDF is worse than the abstract. And a recovery only
        # counts if it clears the same threshold that made this page look thin
        # in the first place — otherwise a repository *record page* (title,
        # authors, a 200-word summary) passes for full text just by being
        # marginally longer than the publisher's abstract.
        recovered_len = len(recovered.content or "")
        if recovered_len <= len(result.content or ""):
            continue
        if recovered_len < settings.oa_min_full_text_chars:
            log.debug(
                "Open-access candidate %s is still not full text (%d chars)",
                loc.url,
                recovered_len,
            )
            continue

        return recovered, loc

    return result, None
