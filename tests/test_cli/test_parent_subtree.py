"""Check literal parent paths across note selection entry points."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note
from hyperresearch.core.vault import Vault

PARENT = "area_100%!"
MATCHES = {"exact", "descendant"}


@pytest.fixture
def parent_vault(tmp_vault: Vault, monkeypatch: pytest.MonkeyPatch) -> Vault:
    monkeypatch.chdir(tmp_vault.root)
    for title, parent in [
        ("Exact", PARENT),
        ("Descendant", f"{PARENT}/child"),
        ("Underscore sibling", "areaX100%!/child"),
        ("Percent sibling", "area_100other!/child"),
        ("Prefix sibling", f"{PARENT}-other/child"),
        ("Unscoped", None),
    ]:
        write_note(tmp_vault.notes_dir, title, body="Example note.", parent=parent)
    tmp_vault.auto_sync()
    return tmp_vault


def test_batch_status_keeps_wildcard_siblings_untouched(parent_vault: Vault) -> None:
    result = CliRunner().invoke(app, ["batch", "set-status", "review", "--parent", PARENT, "--json"])

    assert result.exit_code == 0, result.output
    assert set(json.loads(result.output)["data"]["modified"]) == MATCHES
    rows = parent_vault.db.execute("SELECT id FROM notes WHERE status = 'review'")
    assert {row["id"] for row in rows} == MATCHES


def test_export_vault_keeps_wildcard_siblings_out(parent_vault: Vault, tmp_path: Path) -> None:
    dest = tmp_path / "export"
    result = CliRunner().invoke(app, ["export", "vault", str(dest), "--parent", PARENT, "--json"])

    assert result.exit_code == 0, result.output
    assert {row["id"] for row in json.loads(result.output)["data"]["exported"]} == MATCHES
    assert {path.stem for path in dest.rglob("*.md")} == MATCHES


def test_list_notes_keeps_wildcard_siblings_out(
    parent_vault: Vault, monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = pytest.importorskip("hyperresearch.mcp.server")
    monkeypatch.setattr(server, "_vault", parent_vault)

    assert {row["id"] for row in json.loads(server.list_notes(parent=PARENT))} == MATCHES

def test_topic_show_keeps_wildcard_siblings_out(parent_vault: Vault) -> None:
    result = CliRunner().invoke(app, ["topic", "show", PARENT, "--json"])

    assert result.exit_code == 0, result.output
    assert {row["id"] for row in json.loads(result.output)["data"]["notes"]} == MATCHES
