"""Cite-check — does each citation actually support its sentence?

The FACT half of research quality, self-measured before ship instead of by
an external benchmark. Three layers:

1. `extract_pairs(report_text, conn)` — pure parsing. Splits the report into
   sentences and binds each citation marker to its sentence, for BOTH
   citation styles: numbered `[N]` (resolved through the `## Sources`
   section) and `[[note-id]]` wikilinks.

2. `triage_pairs(pairs, conn)` — mechanical tier. A pair auto-passes when
   the sentence's numbers or a long word-overlap window appear in the cited
   note's claims (`quoted_support` / `numbers`) — no LLM needed for the
   bulk. The remainder is marked `needs-llm` for the cite-checker agent.

3. The `hyperresearch-cite-checker` agent (step 14.5) verifies the
   needs-llm tail against the actual note bodies and emits findings the
   patcher applies. Verdicts: supported | partially-supported |
   unsupported | wrong-source.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from hyperresearch.core.fetcher import existing_live_note_for_url
from hyperresearch.core.patterns import WIKI_LINK_RE, mask_code
from hyperresearch.core.scholar import DOI_RE, extract_doi

# Sentence split: period/question/exclamation followed by space+capital, or newline.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z一-鿿])|\n+")
_NUMBERED_CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_SOURCES_ENTRY_RE = re.compile(r"^\s*\[(\d{1,3})\]\s+(.+)$")
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*%?")
# A link-reference definition (`[7]: https://...`) is a whole line and cites nothing.
_LINK_DEF_RE = re.compile(r"^\s*\[\d+\]:")

# Sentences carrying these are checked at 100% regardless of sampling.
_STRONG_MARKERS = ("%", "$", "billion", "million", "increase", "decrease", "grew", "fell")


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence in `text`, surrounding whitespace excluded."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in [*_SENTENCE_SPLIT_RE.finditer(text), None]:
        end = m.start() if m else len(text)
        piece = text[pos:end]
        if piece.strip():
            start = pos + len(piece) - len(piece.lstrip())
            spans.append((start, pos + len(piece.rstrip())))
        if m:
            pos = m.end()
    return spans


def _doi_key(url: str) -> str | None:
    """The DOI or arXiv id a link names, lower-cased, or None.

    extract_doi is what fills notes.doi at fetch time, so its result is the
    key for that column.
    """
    # urlsplit raises ValueError on a host it cannot parse
    # (`https://example.com]`, or a bare domain written as `[url](url)`);
    # such a link names no DOI.
    try:
        doi = extract_doi(url)
        path = urlparse(url).path
    except ValueError:
        return None
    # A `(` left open means the DOI was cut (see below), or the link was:
    # `.../S0140-6736(20)` loses its `)` to the caller's rstrip.
    if not doi or doi.count("(") > doi.count(")"):
        return None
    # DOI_RE stops at `)`, which Elsevier PII and Wiley SICI DOIs contain, and
    # fetch stores the cut value, so one journal's papers share a key. A DOI
    # the path runs on past (beyond a closing `>` or quote) is not looked up.
    m = DOI_RE.search(path)
    if m and path[m.end():].strip(">\"'"):
        return None
    return doi.lower()


def _note_for_url(url: str, conn) -> str | None:
    """The vault note saved from this exact URL, or None.

    The `sources` table alone is not enough. Removing a note leaves its
    sources row with note_id NULL, and a note written again for the same
    work (`note new --source URL`) holds the URL only in its own `source`
    field.
    """
    row = existing_live_note_for_url(conn, url)
    if row:
        return row["note_id"]
    row = conn.execute("SELECT id FROM notes WHERE source = ? ORDER BY id", (url,)).fetchone()
    if row:
        return row["id"]
    return None


def _note_with_doi(url: str, conn) -> str | None:
    """The one note whose `doi` is the link's DOI, or None.

    A report may cite a paper by its doi.org link while the note was saved
    from another address. Tried after the title: fetch fills `notes.doi` from
    the first DOI after a "DOI" label in a page's body when the page has no
    DOI meta tag, so a news item or review can hold the DOI of a paper it only
    cites. Two notes holding one DOI say nothing about which is the paper.
    """
    doi = _doi_key(url)
    if not doi:
        return None
    rows = conn.execute("SELECT id FROM notes WHERE lower(doi) = ? LIMIT 2", (doi,)).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def _note_holding_doi(url: str, conn) -> str | None:
    """A note saved from another address that holds the link's DOI, or None.

    The weakest match, tried after the title: an address can hold the DOI of
    a work it only lists or searches for.
    """
    doi = _doi_key(url)
    if not doi:
        return None
    # A DOI inside another address ends where the URL does or at its query or
    # fragment; `/` is part of many DOIs. Without the bound, 10.1000/abc would
    # match the address of 10.1000/abc1.
    bounded = re.compile(re.escape(doi) + r"(?=$|[?#&])")
    for row in conn.execute(
        "SELECT id, source FROM notes WHERE instr(lower(source), ?) > 0 ORDER BY id", (doi,)
    ):
        if bounded.search(row["source"].lower()):
            return row["id"]
    return None


def parse_sources_section(report_text: str, conn) -> dict[str, str | None]:
    """Map `[N]` -> note_id by matching Sources-section URLs/titles to the vault."""
    mapping: dict[str, str | None] = {}
    in_sources = False
    for line in report_text.splitlines():
        if re.match(r"^##\s+(Sources|References)\b", line, re.IGNORECASE):
            in_sources = True
            continue
        if in_sources and line.startswith("## "):
            break
        if not in_sources:
            continue
        m = _SOURCES_ENTRY_RE.match(line)
        if not m:
            continue
        num, rest = m.group(1), m.group(2)
        note_id = None
        url = None
        url_m = re.search(r"https?://\S+", rest)
        if url_m:
            url = url_m.group(0).rstrip(".,)")
            note_id = _note_for_url(url, conn)
        if note_id is None:
            title = rest.split("http")[0].strip(" .–-")
            if title:
                row = conn.execute(
                    "SELECT id FROM notes WHERE title = ? COLLATE NOCASE", (title,)
                ).fetchone()
                if row:
                    note_id = row["id"]
        if note_id is None and url:
            note_id = _note_with_doi(url, conn)
        if note_id is None and url:
            note_id = _note_holding_doi(url, conn)
        mapping[num] = note_id
    return mapping


def extract_pairs(report_text: str, conn) -> list[dict]:
    """All (sentence, note_id) citation bindings in the report.

    Pairs whose citation can't be resolved to a vault note get
    note_id=None and an `unresolved` reason, because the reasons call for
    different handling:

      no-sources-entry  - a `[N]` marker with no `[N]` line in the Sources
                          section: a fabricated or mangled citation.
      unknown-note-id   - a `[[note-id]]` naming no vault note: the same.
      unresolved-entry  - the Sources entry exists but neither its URL nor its
                          title matches a vault note. The citation may still be
                          sound; check the entry before calling it a finding.
    """
    numbered_map = parse_sources_section(report_text, conn)
    known_ids = {row["id"] for row in conn.execute("SELECT id FROM notes")}

    # Strip the Sources section from the checked body
    body = re.split(r"^##\s+(?:Sources|References)\b", report_text, maxsplit=1, flags=re.M | re.I)[0]

    # Code and link-reference definitions hold brackets that are not citations
    # (`arr[0]`, `[7]: https://...`). mask_code blanks code at its own length
    # and keeps line structure, so a line it empties (a fenced block) or a
    # definition line is dropped, and on every other line an offset means the
    # same character in both texts. Each line is split into sentences once,
    # on the report's text, which is what the patcher edits by; markers are
    # scanned in the same span of the masked line.
    sentences: list[str] = []
    scanned: list[str] = []
    for line, masked in zip(body.split("\n"), mask_code(body).split("\n"), strict=True):
        if not masked.strip() or _LINK_DEF_RE.match(line):
            continue
        for start, end in _sentence_spans(line):
            sentences.append(line[start:end])
            scanned.append(masked[start:end])

    pairs: list[dict] = []
    for sentence, text in zip(sentences, scanned, strict=True):
        cited: list[tuple[str, str | None, str | None]] = []
        for m in _NUMBERED_CITE_RE.finditer(text):
            nums = re.split(r"\s*,\s*", m.group(1))
            # Citations count from 1: `[0]`, `[0, 3]` and `[007]` are an index,
            # an interval or an id, unless the Sources section numbers its
            # entries that way.
            if any(n.startswith("0") and n not in numbered_map for n in nums):
                continue
            for num in nums:
                if num in numbered_map:
                    note_id = numbered_map[num]
                    cited.append((f"[{num}]", note_id, None if note_id else "unresolved-entry"))
                elif numbered_map:
                    # Only once a `[N] ...` Sources line parsed: without one,
                    # `[N]` is not the report's citation style and the marker
                    # is not a citation.
                    cited.append((f"[{num}]", None, "no-sources-entry"))
        for m in WIKI_LINK_RE.finditer(text):
            target = m.group(1).strip()
            if target in known_ids:
                cited.append((f"[[{target}]]", target, None))
            else:
                cited.append((f"[[{target}]]", None, "unknown-note-id"))
        for marker, note_id, reason in cited:
            pair = {
                "sentence": sentence,
                "marker": marker,
                "note_id": note_id,
                "numbers": _NUMBER_RE.findall(sentence),
                "strong": any(k in sentence.lower() for k in _STRONG_MARKERS) or bool(_NUMBER_RE.search(sentence)),
            }
            if reason:
                pair["unresolved"] = reason
            pairs.append(pair)
    return pairs


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def triage_pairs(pairs: list[dict], conn) -> dict:
    """Mechanical verification tier.

    Verdicts per pair:
      dangling            — citation resolves to no vault note (finding)
      supported-mechanical — sentence numbers / long overlap found in the
                            cited note's claims (auto-pass)
      needs-llm           — the cite-checker agent must judge it
    """
    claims_by_note: dict[str, list[dict]] = {}

    def _claims(note_id: str) -> list[dict]:
        if note_id not in claims_by_note:
            rows = conn.execute(
                "SELECT claim, quoted_support, numbers FROM claims WHERE note_id = ?",
                (note_id,),
            ).fetchall()
            claims_by_note[note_id] = [dict(r) for r in rows]
        return claims_by_note[note_id]

    supported = 0
    dangling = 0
    needs_llm = []
    for pair in pairs:
        if pair["note_id"] is None:
            pair["verdict"] = "dangling"
            dangling += 1
            continue
        matched = False
        note_claims = _claims(pair["note_id"])
        blob = _norm(" ".join(
            (c["claim"] or "") + " " + (c["quoted_support"] or "") + " " + (c["numbers"] or "")
            for c in note_claims
        ))
        if blob:
            nums = [n for n in pair["numbers"] if len(n.replace(",", "")) >= 2]
            if nums and all(n.replace(",", "") in blob.replace(",", "") for n in nums):
                matched = True
            elif not nums:
                # Long word-overlap window: any 6-consecutive-word shingle of the
                # sentence found in the claims blob
                words = _norm(pair["sentence"]).split()
                for i in range(len(words) - 5):
                    if " ".join(words[i : i + 6]) in blob:
                        matched = True
                        break
        if matched:
            pair["verdict"] = "supported-mechanical"
            supported += 1
        else:
            pair["verdict"] = "needs-llm"
            needs_llm.append(pair)

    return {
        "total": len(pairs),
        "supported_mechanical": supported,
        "dangling": dangling,
        "needs_llm": len(needs_llm),
        "pairs": pairs,
    }


def sample_needs_llm(pairs: list[dict], sample_rate: float = 0.6) -> list[dict]:
    """Deterministic sampling of the LLM tier: 100% of strong (number-bearing)
    sentences, `sample_rate` of the rest. No RNG — reproducible across resumes.

    A weak pair is kept whenever floor(seen * rate) steps up, which spreads the
    kept pairs evenly and hits the rate exactly. The old every-k-th rule
    rounded 1/rate, so 0.6 became every 2nd and sampled 50%.
    """
    out = []
    weak_seen = 0
    rate = min(max(sample_rate, 0.0), 1.0)
    for pair in pairs:
        if pair.get("verdict") != "needs-llm":
            continue
        if pair["strong"]:
            out.append(pair)
            continue
        weak_seen += 1
        if int(weak_seen * rate) > int((weak_seen - 1) * rate):
            out.append(pair)
    return out


def write_pairs_file(vault, vault_tag: str, report_path, sample_rate: float = 0.6) -> dict:
    """Extract + triage + sample; write cite-check-pairs.json into the run dir."""
    report_text = report_path.read_text(encoding="utf-8-sig")
    pairs = extract_pairs(report_text, vault.db)
    triaged = triage_pairs(pairs, vault.db)
    to_check = sample_needs_llm(triaged["pairs"], sample_rate)

    run_dir = vault.run_dir(vault_tag)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "report": str(report_path),
        "summary": {k: v for k, v in triaged.items() if k != "pairs"},
        "sampled_for_llm": to_check,
        "dangling": [p for p in triaged["pairs"] if p["verdict"] == "dangling"],
    }
    (run_dir / "cite-check-pairs.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out
