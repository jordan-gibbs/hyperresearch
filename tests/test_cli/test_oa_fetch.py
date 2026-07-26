"""End-to-end open-access recovery through both fetch paths — offline.

Guards the wiring rather than the resolution logic (that lives in
tests/test_core/test_oa_recovery.py): the swap has to survive `write_note`,
frontmatter re-parsing, and both the single and batch CLI commands, and it has
to stay visible in every output the user actually sees.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult

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

    from hyperresearch.core import oa, scholar
    from hyperresearch.web import crawl4ai_provider

    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _AbstractOnlyProvider())
    monkeypatch.setattr(
        scholar, "_http_get_json", lambda url: UNPAYWALL if "unpaywall" in url else None
    )
    monkeypatch.setattr(oa.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])
    monkeypatch.setattr(
        crawl4ai_provider,
        "_fetch_pdf",
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


def test_recovery_is_off_without_an_email(tmp_path: Path, monkeypatch):
    """Default install: Unpaywall is skipped, so a closed paper stays an
    abstract rather than silently reaching for a shared placeholder address."""
    runner.invoke(app, ["init", str(tmp_path / "kb2"), "--name", "No Email"])
    os.chdir(tmp_path / "kb2")

    from hyperresearch.core import oa, scholar

    seen: list[str] = []
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _AbstractOnlyProvider())
    monkeypatch.setattr(oa.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])

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
