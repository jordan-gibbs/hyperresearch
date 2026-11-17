"""Commands that rewrite a note's frontmatter keep the user's own keys, and
notes with scalar, empty or numeric tags and ids reach the index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()

PAPER = (
    "---\n"
    "title: Paper\n"
    "authors: [Vaswani, Shazeer]\n"
    "year: 2017\n"
    "url: https://arxiv.org/abs/1706.03762\n"
    "---\n"
    "The Transformer relies entirely on attention mechanisms, dispensing with "
    "recurrence and convolutions entirely.\n"
)


@pytest.fixture
def vault_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "v")])
    assert result.exit_code == 0, result.output
    root = tmp_path / "v"
    monkeypatch.chdir(root)
    return root


def _seed_paper(root: Path) -> Path:
    path = root / "research" / "notes" / "paper.md"
    path.write_text(PAPER, encoding="utf-8")
    result = runner.invoke(app, ["sync", "--json"])
    assert result.exit_code == 0, result.output
    return path


def _assert_user_keys_kept(path: Path) -> dict:
    fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])
    assert fm["authors"] == ["Vaswani", "Shazeer"]
    assert fm["year"] == 2017
    assert fm["url"] == "https://arxiv.org/abs/1706.03762"
    return fm


def test_note_update_keeps_user_keys(vault_root):
    path = _seed_paper(vault_root)
    result = runner.invoke(app, ["note", "update", "paper", "--status", "review", "--json"])
    assert result.exit_code == 0, result.output
    assert _assert_user_keys_kept(path)["status"] == "review"


def test_batch_set_status_keeps_user_keys(vault_root):
    path = _seed_paper(vault_root)
    result = runner.invoke(app, ["batch", "set-status", "review", "--json"])
    assert result.exit_code == 0, result.output
    assert _assert_user_keys_kept(path)["status"] == "review"


def test_repair_enrich_keeps_user_keys(vault_root):
    path = _seed_paper(vault_root)
    result = runner.invoke(app, ["repair", "--json"])
    assert result.exit_code == 0, result.output
    assert _assert_user_keys_kept(path).get("summary")


def test_mcp_update_note_keeps_user_keys(vault_root):
    mcp = pytest.importorskip("hyperresearch.mcp.server")
    path = _seed_paper(vault_root)
    mcp._vault = None  # module-global cache; force rediscovery under tmp_path
    try:
        out = json.loads(mcp.update_note("paper", status="review"))
    finally:
        mcp._vault = None
    assert out["ok"] is True
    assert _assert_user_keys_kept(path)["status"] == "review"


def test_repair_writes_scalar_tag_back_as_one_tag(vault_root):
    path = vault_root / "research" / "notes" / "obs.md"
    path.write_text(
        "---\ntitle: Obsidian style\ntags: research\n---\n"
        "Some body text long enough to produce an automatic summary line here.\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["repair", "--json"])
    assert result.exit_code == 0, result.output
    fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])
    assert fm["tags"] == ["research"]


def test_sync_indexes_scalar_empty_and_numeric_tags_and_ids(vault_root):
    notes = vault_root / "research" / "notes"
    created = "created: '2026-01-01T00:00:00Z'\n"
    (notes / "t1.md").write_text(f"---\ntitle: Scalar Tag\nid: t1\ntags: ml\n{created}---\n\nalpha body\n")
    (notes / "t2.md").write_text(f"---\ntitle: Empty Tags\nid: t2\ntags:\n{created}---\n\nalpha body\n")
    (notes / "t3.md").write_text(f"---\ntitle: Year Tag\nid: t3\ntags: [2024, ml]\n{created}---\n\nalpha body\n")
    (notes / "c.md").write_text(f"---\ntitle: Numeric id\nid: 12345\n{created}---\n\nalpha body\n")

    result = runner.invoke(app, ["sync", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["errors"] == []
    assert data["added"] == 4

    from hyperresearch.core.vault import Vault

    db = Vault.discover().db
    tags = {
        (r["note_id"], r["tag"]) for r in db.execute("SELECT note_id, tag FROM tags")
    }
    assert tags == {("t1", "ml"), ("t3", "2024"), ("t3", "ml")}
    ids = {r["id"] for r in db.execute("SELECT id FROM notes")}
    assert {"t1", "t2", "t3", "12345"} <= ids
