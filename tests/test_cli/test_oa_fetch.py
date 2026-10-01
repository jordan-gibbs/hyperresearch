"""End-to-end open-access recovery through both fetch paths — offline.

Guards the wiring rather than the resolution logic (that lives in
tests/test_core/test_oa_recovery.py): the swap has to survive `write_note`,
frontmatter re-parsing, and both the single and batch CLI commands, and it has
to stay visible in every output the user actually sees.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult
from hyperresearch.web.base import get_provider as _real_get_provider

runner = CliRunner()

PAPER_URL = "https://doi.org/10.1234/abc"
ABSTRACT = "We study widgets. " * 40
FULL_TEXT = "Full text of the widget paper, section by section. " * 900

UNPAYWALL = {
    "is_oa": True,
    "best_oa_location": {
        "url_for_pdf": "https://repo.example.org/widgets.pdf",
        "version": "acceptedVersion",
        "license": "cc-by-nc",
        "host_type": "repository",
    },
}


class _AbstractOnlyProvider:
    name = "fake"

    def fetch(self, url):
        return WebResult(url=url, title="Widget Paper", content=ABSTRACT)

    def fetch_many(self, urls):
        return [self.fetch(u) for u in urls]


class _BlockedProvider:
    """The publisher refuses outright — no page, no abstract, nothing."""

    name = "fake-blocked"

    def fetch(self, url):
        raise RuntimeError("Client error '403 Forbidden'")

    def fetch_many(self, urls):
        raise RuntimeError("Client error '403 Forbidden'")


class _CertRefusingProvider:
    """The certificate did not verify, so the fetch was refused rather than
    failing. Both entry points raise, as the PDF lane does."""

    name = "fake-cert"

    def fetch(self, url):
        from hyperresearch.web.safe_http import CertVerificationError

        # The PDF lane's wording: the opt-out names a config section.
        raise CertVerificationError(
            f"certificate verification failed for {url!r}: CERTIFICATE_VERIFY_FAILED. "
            "If this host is a known cert-broken mirror you trust, set "
            "pdf_verify_tls = false under [fetch] in config.toml."
        )

    def fetch_many(self, urls):
        return [self.fetch(u) for u in urls]


class _LoginWallProvider:
    name = "fake-wall"

    def fetch(self, url):
        return WebResult(
            url=url,
            title="Sign in to continue",
            content="Please sign in to your institution to continue.",
        )

    def fetch_many(self, urls):
        return [self.fetch(u) for u in urls]


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "OA Test"])
    assert result.exit_code == 0
    root = tmp_path / "kb"

    cfg = root / ".hyperresearch" / "config.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace(
            'contact_email = ""', 'contact_email = "tester@example.org"'
        ),
        encoding="utf-8",
    )

    from hyperresearch.core import scholar
    from hyperresearch.web import pdf as pdf_lane

    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _AbstractOnlyProvider())
    monkeypatch.setattr(
        scholar, "_http_get_json", lambda url: UNPAYWALL if "unpaywall" in url else None
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])
    monkeypatch.setattr(
        pdf_lane,
        "fetch_pdf",
        lambda url, settings: WebResult(url=url, title="Widget Paper", content=FULL_TEXT),
    )
    return root


def _read_note(vault_dir: Path, note_id: str):
    from hyperresearch.core.frontmatter import parse_frontmatter

    path = next(p for p in (vault_dir / "research" / "notes").glob(f"{note_id}.md"))
    return parse_frontmatter(path.read_text(encoding="utf-8-sig"))


def test_single_fetch_recovers_and_discloses(vault_dir: Path):
    os.chdir(vault_dir)
    result = runner.invoke(app, ["fetch", PAPER_URL, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]

    # The swap is reported in the machine-readable output
    assert data["oa"]["url"] == "https://repo.example.org/widgets.pdf"
    assert data["oa"]["resolver"] == "unpaywall"
    assert data["oa"]["version"] == "acceptedVersion"
    assert data["oa"]["replaced_chars"] == len(ABSTRACT)

    meta, body = _read_note(vault_dir, data["note_id"])

    # source still points at what was asked for; the body says where it came from
    assert meta.source == PAPER_URL
    assert meta.doi == "10.1234/abc"
    assert meta.oa_url == "https://repo.example.org/widgets.pdf"
    assert meta.oa_source == "unpaywall"
    assert meta.oa_version == "acceptedVersion"
    assert meta.oa_license == "cc-by-nc"

    assert body.startswith("> [!] **Open-access full text substituted.**")
    assert "accepted manuscript" in body
    assert "Quote this source with care" in body
    assert FULL_TEXT[:60] in body


def test_batch_fetch_recovers_and_discloses(vault_dir: Path):
    os.chdir(vault_dir)
    result = runner.invoke(app, ["fetch-batch", PAPER_URL, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]

    assert data["oa_recovered"] == 1
    note = data["notes_created"][0]
    assert note["oa"]["resolver"] == "unpaywall"

    meta, body = _read_note(vault_dir, note["note_id"])
    assert meta.source == PAPER_URL
    assert meta.oa_url == "https://repo.example.org/widgets.pdf"
    assert body.startswith("> [!] **Open-access full text substituted.**")


def test_note_show_surfaces_the_substitution(vault_dir: Path):
    """The body banner sits inside the untrusted-source fence, so anything
    reading notes structurally needs the swap in the metadata too."""
    os.chdir(vault_dir)
    fetched = json.loads(runner.invoke(app, ["fetch", PAPER_URL, "--json"]).output)["data"]

    shown = runner.invoke(app, ["note", "show", fetched["note_id"], "--json"])
    assert shown.exit_code == 0
    data = json.loads(shown.output)["data"]

    assert data["source"] == PAPER_URL
    assert data["oa"]["url"] == "https://repo.example.org/widgets.pdf"
    assert data["oa"]["version"] == "acceptedVersion"
    assert data["oa"]["body_is_not_from_source"] is True


def test_plain_note_has_no_oa_block(vault_dir: Path, monkeypatch):
    """No false alarms: an ordinary fetch must not grow an `oa` key."""
    os.chdir(vault_dir)
    from hyperresearch.core import scholar

    monkeypatch.setattr(scholar, "_http_get_json", lambda url: None)
    fetched = json.loads(
        runner.invoke(app, ["fetch", "https://blog.example.com/post", "--json"]).output
    )["data"]
    assert "oa" not in fetched

    shown = json.loads(
        runner.invoke(app, ["note", "show", fetched["note_id"], "--json"]).output
    )["data"]
    assert "oa" not in shown


def test_blocked_fetch_is_rescued(vault_dir: Path, monkeypatch):
    """A 403 used to lose the paper entirely — the fetch aborted long before
    recovery ran. The DOI is in the URL and a legal copy exists, so it should
    produce a note instead."""
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _BlockedProvider())

    result = runner.invoke(app, ["fetch", PAPER_URL, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]

    assert data["oa"]["kind"] == "rescued"
    assert data["oa"]["nothing_from_source"] is True
    assert "403" in data["oa"]["blocked_reason"]

    meta, body = _read_note(vault_dir, data["note_id"])
    assert meta.source == PAPER_URL          # still what was asked for
    assert meta.doi == "10.1234/abc"         # taken from the URL, not the body
    assert meta.oa_recovery_kind == "rescued"
    assert meta.source_domain == "doi.org"   # not the substitute's host
    assert body.startswith("> [!] **Recovered from an open-access copy.")
    assert "NOTHING in this note came from the source URL" in body

    shown = json.loads(
        runner.invoke(app, ["note", "show", data["note_id"], "--json"]).output
    )["data"]
    assert shown["oa"]["kind"] == "rescued"
    assert shown["oa"]["nothing_from_source"] is True


def test_login_wall_is_rescued_instead_of_escalated(vault_dir: Path, monkeypatch):
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _LoginWallProvider())

    result = runner.invoke(app, ["fetch", PAPER_URL, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]
    assert data["oa"]["kind"] == "rescued"
    assert "login wall" in data["oa"]["blocked_reason"]

    # Nothing queued for the human — we already have the paper.
    queued = json.loads(
        runner.invoke(app, ["escalation", "list", "--status", "queued", "--json"]).output
    )["data"]
    assert not queued["items"]


def test_blocked_fetch_without_a_copy_still_fails(vault_dir: Path, monkeypatch):
    """The invariant holds: rescue only ever turns a failure into a note. When
    no copy exists the command fails exactly as it always did."""
    os.chdir(vault_dir)
    from hyperresearch.core import scholar

    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _BlockedProvider())
    monkeypatch.setattr(scholar, "_http_get_json", lambda url: None)

    result = runner.invoke(app, ["fetch", PAPER_URL, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "FETCH_ERROR"


def _rescue_spy(monkeypatch) -> list[str]:
    """Record every rescue attempt without performing one."""
    from hyperresearch.core import oa

    calls: list[str] = []

    def fake_rescue(vault, prov, url, doi):
        calls.append(url)
        return None, None

    monkeypatch.setattr(oa, "rescue_full_text", fake_rescue)
    return calls


def test_cert_refusal_is_not_rescued(vault_dir: Path, monkeypatch):
    """A refused certificate must stay a refusal: the command fails with
    TLS_CERT_INVALID and writes no note. Offered to the rescue, it came back
    as an ordinary rescued note (exit 0, `kind: "rescued"`), with the refusal
    only as free text in `oa.blocked_reason`. Under this vault's stubs the
    rescue WOULD succeed, so the spy proves the guard, not a missing copy."""
    os.chdir(vault_dir)
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _CertRefusingProvider()
    )
    attempts = _rescue_spy(monkeypatch)

    result = runner.invoke(app, ["fetch", PAPER_URL, "--json"])
    assert attempts == []  # the refusal never reached the rescue
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_code"] == "TLS_CERT_INVALID"
    assert "pdf_verify_tls" in payload["error"]
    assert list((vault_dir / "research" / "notes").glob("*.md")) == []


def test_batch_cert_refusal_is_a_loud_skip_not_a_rescue(vault_dir: Path, monkeypatch):
    """Same rule on the batch path, which reaches the rescue by a different
    route: a per-URL failure is recorded and every recorded failure is then
    offered to the rescue. A cert refusal is held back from that list and stays
    in `failed_urls`, so the caller still sees the URL it lost."""
    os.chdir(vault_dir)
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _CertRefusingProvider()
    )
    attempts = _rescue_spy(monkeypatch)

    result = runner.invoke(app, ["fetch-batch", PAPER_URL, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]

    assert attempts == []
    assert data["oa_rescued"] == 0
    assert data["notes_created"] == []
    assert [f["url"] for f in data["failed_urls"]] == [PAPER_URL]
    assert "certificate" in data["failed_urls"][0]["error"]
    # The one machine-readable signal: `error` is free text and `phase` is
    # shared with every other failure.
    assert data["failed_urls"][0]["reason"] == "tls_cert_invalid"


def test_batch_skip_line_survives_brackets_in_the_url(vault_dir: Path, monkeypatch):
    """The URL is external text too. A bracketed query parameter is a tag to
    Rich, and a closing one (`[/b]`) raised MarkupError inside the handler,
    which ended the whole batch."""
    os.chdir(vault_dir)
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _CertRefusingProvider()
    )
    _rescue_spy(monkeypatch)

    query = "?filter[type]=pdf&x=[/b]"
    result = runner.invoke(app, ["fetch-batch", PAPER_URL + query])
    assert result.exit_code == 0
    assert "SKIPPED (TLS certificate invalid):" in result.output
    # Twice inside the message (the fallback line, then the skip), once bare.
    assert result.output.count(query) == 3


def test_batch_failure_line_survives_brackets_in_the_url_and_message(
    vault_dir: Path, monkeypatch
):
    """The per-URL failure line prints two pieces of external text, the URL
    and the exception message, and escapes both: a closing tag in either one
    raised MarkupError inside the handler."""
    os.chdir(vault_dir)

    class _BracketFailingProvider:
        name = "fake-brackets"

        def fetch(self, url):
            raise RuntimeError("upstream said [/i] no")

        def fetch_many(self, urls):
            raise RuntimeError("batch lane down")

    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _BracketFailingProvider()
    )
    _rescue_spy(monkeypatch)

    query = "?filter[type]=pdf&x=[/b]"
    result = runner.invoke(app, ["fetch-batch", PAPER_URL + query])
    assert result.exit_code == 0
    # Rich wraps at the terminal width, so compare with whitespace collapsed.
    flat = " ".join(result.output.split())
    assert f"Failed (batch-fallback): {PAPER_URL + query} — upstream said [/i] no" in flat


def test_batch_rescue_lines_survive_brackets_in_the_failure(vault_dir: Path, monkeypatch):
    """With the failure line escaped the batch goes on to the rescue, whose
    lines print external text after the note is written: the URL, the
    copy's title, URL and version, and the failure. A closing tag in any of
    them raised MarkupError with the note file on disk and no index row, and
    the next run wrote a second note. Each field carries its own tag here."""
    os.chdir(vault_dir)
    from hyperresearch.core import scholar
    from hyperresearch.web import pdf as pdf_lane

    oa_pdf = UNPAYWALL["best_oa_location"]["url_for_pdf"] + "?v=[/u]"
    unpaywall = {
        "is_oa": True,
        "best_oa_location": {
            **UNPAYWALL["best_oa_location"], "url_for_pdf": oa_pdf, "version": "accepted[/v]Version"
        },
    }
    monkeypatch.setattr(
        scholar, "_http_get_json", lambda url: unpaywall if "unpaywall" in url else None
    )
    monkeypatch.setattr(
        pdf_lane,
        "fetch_pdf",
        lambda url, settings: WebResult(url=url, title="Widget [/b] Paper", content=FULL_TEXT),
    )
    url = PAPER_URL + "?x=[/s]"

    class _BracketBlockedProvider:
        name = "fake-blocked-brackets"

        def fetch(self, url):
            raise RuntimeError("Client error '403 Forbidden' [/i]")

        def fetch_many(self, urls):
            raise RuntimeError("Client error '403 Forbidden' [/i]")

    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _BracketBlockedProvider()
    )

    result = runner.invoke(app, ["fetch-batch", url])
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert f"Blocked — recovered an open-access copy: {url}" in flat
    assert "+ Widget [/b] Paper" in flat
    assert f"body from: {oa_pdf} (accepted[/v]Version," in flat
    assert "source never read (fetch failed: Client error '403 Forbidden' [/i])" in flat
    notes = list((vault_dir / "research" / "notes").glob("*.md"))
    assert len(notes) == 1
    listed = json.loads(runner.invoke(app, ["search", "Widget", "--json"]).output)["data"]
    assert len(listed["results"]) == 1


@pytest.mark.parametrize(
    ("command", "lines"),
    [
        (["fetch", PAPER_URL], ["Fetch refused (TLS certificate invalid):"]),
        (
            ["fetch-batch", PAPER_URL],
            ["Batch fetch failed:", "SKIPPED (TLS certificate invalid):"],
        ),
    ],
)
def test_cert_refusal_console_line_keeps_the_config_hint(
    vault_dir: Path, monkeypatch, command, lines
):
    """The opt-out reads "[fetch]", which Rich takes for a markup tag and
    drops, leaving "under  in config.toml". Every line that prints the
    message escapes it: the provider's `fetch_many` raises first, so the
    batch's fallback line prints the message before the skip does."""
    os.chdir(vault_dir)
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _CertRefusingProvider()
    )
    _rescue_spy(monkeypatch)

    result = runner.invoke(app, command)
    for line in lines:
        assert line in result.output
    assert result.output.count("[fetch]") == len(lines)


# Shaped like a PDF, so the PDF lane takes it, and on doi.org, the one host whose
# URL `extract_doi` reads a DOI from: after a failed fetch there is no page to
# read one out of, and without a DOI there is no rescue.
PDF_URL = "https://doi.org/10.1234/abc.pdf"
LANDING_PAGE = "https://repo.example.org/widgets"
UNPAYWALL_LANDING_ONLY = {
    "is_oa": True,
    "best_oa_location": {"url": LANDING_PAGE, "version": "publishedVersion"},
}


def test_visible_fetch_cert_refusal_never_reaches_the_unverified_lane(
    vault_dir: Path, monkeypatch
):
    """The route on which a certificate refusal led to an unverified fetch. With
    --visible (or an auto-visible domain) and a login profile, the crawl4ai
    provider fetches pages through `_fetch_visible`, a Playwright window
    launched with ignore_https_errors=True by design (#137: some walled sites
    have broken chains), while its PDF lane verifies first. The rescue reuses
    that provider for landing-page candidates, so a certificate refusal on
    the PDF lane was followed by an unverified fetch of the open-access
    landing page. The source has to be a URL the PDF lane takes whose DOI is
    in the URL, a doi.org link ending in .pdf here. Hermetic: the real
    provider with the PDF lane and the window stubbed; no browser starts."""
    c4 = pytest.importorskip(
        "hyperresearch.web.crawl4ai_provider", reason="crawl4ai not importable"
    )
    from hyperresearch.core import scholar
    from hyperresearch.web.safe_http import CertVerificationError

    os.chdir(vault_dir)
    cfg = vault_dir / ".hyperresearch" / "config.toml"
    text = cfg.read_text(encoding="utf-8")
    assert text.count('provider = "builtin"\nprofile = ""\n') == 1
    cfg.write_text(
        text.replace(
            'provider = "builtin"\nprofile = ""\n', 'provider = "crawl4ai"\nprofile = "tester"\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("hyperresearch.web.base.get_provider", _real_get_provider)

    def refuse_pdf(url, settings=None):
        raise CertVerificationError(
            f"certificate verification failed for {url!r}: CERTIFICATE_VERIFY_FAILED. "
            "If this host is a known cert-broken mirror you trust, set "
            "pdf_verify_tls = false under [fetch] in config.toml."
        )

    windows: list[str] = []

    async def fake_visible(self, url):
        windows.append(url)
        return WebResult(url=url, title="Widget Paper", content=FULL_TEXT)

    monkeypatch.setattr(c4, "_fetch_pdf", refuse_pdf)
    monkeypatch.setattr(c4.Crawl4AIProvider, "_fetch_visible", fake_visible)
    # A landing page only, so the candidate goes through the provider rather
    # than the PDF lane.
    monkeypatch.setattr(
        scholar,
        "_http_get_json",
        lambda url: UNPAYWALL_LANDING_ONLY if "unpaywall" in url else None,
    )

    result = runner.invoke(app, ["fetch", PDF_URL, "--visible", "--json"])
    assert windows == []  # the landing page never went through the window
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "TLS_CERT_INVALID"
    assert list((vault_dir / "research" / "notes").glob("*.md")) == []


def test_batch_rescues_blocked_urls_and_clears_them_from_failures(
    vault_dir: Path, monkeypatch
):
    """Batch is where this matters most — the pipeline fetches in waves, so one
    bot-walled publisher drops a whole cluster at once."""
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _BlockedProvider())

    result = runner.invoke(app, ["fetch-batch", PAPER_URL, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]

    assert data["oa_rescued"] == 1
    assert data["failed_urls"] == []  # rescued, therefore no longer lost
    note = data["notes_created"][0]
    assert note["oa"]["kind"] == "rescued"

    meta, body = _read_note(vault_dir, note["note_id"])
    assert meta.source == PAPER_URL
    assert meta.oa_recovery_kind == "rescued"
    assert "NOTHING in this note came from the source URL" in body


def test_rescue_can_be_switched_off(vault_dir: Path, monkeypatch):
    os.chdir(vault_dir)
    cfg = vault_dir / ".hyperresearch" / "config.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace(
            "oa_rescue_blocked = true", "oa_rescue_blocked = false"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _BlockedProvider())

    result = runner.invoke(app, ["fetch", PAPER_URL, "--json"])
    assert result.exit_code == 1


def test_recovery_is_off_without_an_email(tmp_path: Path, monkeypatch):
    """Default install: Unpaywall is skipped, so a closed paper stays an
    abstract rather than silently reaching for a shared placeholder address."""
    runner.invoke(app, ["init", str(tmp_path / "kb2"), "--name", "No Email"])
    os.chdir(tmp_path / "kb2")

    from hyperresearch.core import scholar

    seen: list[str] = []
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _AbstractOnlyProvider())
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])

    def track(url):
        seen.append(url)
        return None

    monkeypatch.setattr(scholar, "_http_get_json", track)

    result = runner.invoke(app, ["fetch", PAPER_URL, "--json"])
    assert result.exit_code == 0
    assert "oa" not in json.loads(result.output)["data"]
    assert not any("unpaywall" in u for u in seen)
    # Europe PMC is still consulted — it needs no key
    assert any("europepmc" in u for u in seen)
