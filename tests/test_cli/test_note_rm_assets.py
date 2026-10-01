"""Which asset files `note rm` removes, and which it keeps.

Fetch names an assets directory after the stem of the note's file at the
time, and the id under that stem can change: sync renames a note's row in
place when its `id:` is rewritten and leaves the files where fetch wrote
them. So the rows decide, not the directory name.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.vault import Vault

runner = CliRunner()


@pytest.fixture
def vault_with_notes(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "kb"
    runner.invoke(app, ["init", str(vault_dir)])
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Alpha Note", "--tag", "test"])
    runner.invoke(app, ["note", "new", "Beta Note", "--tag", "test"])
    runner.invoke(app, ["sync"])
    return vault_dir


def _row(vault_dir: Path, note_id: str, path: Path) -> None:
    """Record `path` as an asset of `note_id`, spelled as given."""
    vault = Vault(vault_dir)
    vault.db.execute(
        "INSERT INTO assets (note_id, type, filename, created_at) VALUES (?, 'image', ?, 't')",
        (note_id, str(path)),
    )
    vault.db.commit()
    vault.close()


def _asset(vault_dir: Path, note_id: str, rel: str, data: bytes = b"x") -> Path:
    """Write research/assets/<rel> and record it as an asset of `note_id`."""
    path = vault_dir / "research" / "assets" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _row(vault_dir, note_id, path)
    return path


def _symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:
        pytest.skip(f"cannot create a symlink here: {exc}")


def _rm(note_id: str) -> dict:
    result = runner.invoke(app, ["note", "rm", note_id, "--force", "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


def test_note_rm_keeps_asset_files_another_note_owns(vault_with_notes):
    """A file another note's assets row names survives the delete, even when
    the note's own row names it too, and so does the directory holding it.
    The row's spelling of the path does not matter: files are matched by
    identity."""
    assets = vault_with_notes / "research" / "assets"
    own = _asset(vault_with_notes, "alpha-note", "alpha-note/own.png", b"a")
    other = assets / "alpha-note" / "other.png"
    other.write_bytes(b"b")
    (assets / "beta-note").mkdir()
    _row(vault_with_notes, "beta-note", assets / "beta-note" / ".." / "alpha-note" / "other.png")
    shared = _asset(vault_with_notes, "alpha-note", "alpha-note/shared.png", b"s")
    _row(vault_with_notes, "beta-note", shared)

    data = _rm("alpha-note")

    assert data.get("removed_assets") == ["research/assets/alpha-note/own.png"]
    assert "assets_not_removed" not in data
    assert not own.exists()
    assert other.read_bytes() == b"b"
    assert shared.read_bytes() == b"s"
    assert (assets / "alpha-note").is_dir()


def test_note_rm_removes_the_files_its_own_rows_name_outside_its_directory(vault_with_notes):
    """After an id rewrite the note's asset rows still point into the
    directory fetch named after the file's stem, `old-id`. Those files go
    with the note, that directory goes once it is empty, another note's
    directory is left alone, and a row naming a file that is already gone
    is not an error. The note's own directory goes too, with a file no row
    names in a subdirectory (fetch can write a file it records no row for)
    and an empty subdirectory."""
    assets = vault_with_notes / "research" / "assets"
    own = _asset(vault_with_notes, "alpha-note", "old-id/figure.png", b"a")
    missing = _asset(vault_with_notes, "alpha-note", "old-id/missing.png")
    missing.unlink()
    other = _asset(vault_with_notes, "beta-note", "beta-note/shot.png", b"b")
    stray = assets / "alpha-note" / "sub" / "stray.png"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"s")
    (assets / "alpha-note" / "empty").mkdir()

    data = _rm("alpha-note")

    assert data.get("removed_assets") == [
        "research/assets/old-id/figure.png",
        "research/assets/alpha-note/sub/stray.png",
    ]
    assert "assets_not_removed" not in data
    assert not own.exists()
    assert not (assets / "old-id").exists()
    assert other.read_bytes() == b"b"
    assert not (assets / "alpha-note").exists()


def test_note_rm_leaves_a_file_its_row_names_outside_research_assets(vault_with_notes, tmp_path):
    """A copy of a vault keeps the original's paths in its rows. Deleting a
    note in the copy must not reach into the original: such a file is left
    alone and reported, and the copy's own directory still goes. Nothing
    above it goes either: research/assets/ stays even once empty."""
    original = tmp_path / "original" / "research" / "assets" / "alpha-note" / "shot.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"o")
    _row(vault_with_notes, "alpha-note", original)
    copy = _asset(vault_with_notes, "alpha-note", "alpha-note/shot.png", b"c")
    loose = _asset(vault_with_notes, "alpha-note", "loose.png", b"l")

    data = _rm("alpha-note")

    assert data.get("removed_assets") == [
        "research/assets/alpha-note/shot.png",
        "research/assets/loose.png",
    ]
    assert data.get("assets_not_removed") == [f"{original}: outside research/assets/, left in place"]
    assert original.read_bytes() == b"o"
    assert not copy.exists() and not loose.exists()
    assert not copy.parent.exists()
    assert loose.parent.is_dir()


def test_note_rm_does_not_walk_a_symlinked_assets_directory(vault_with_notes, tmp_path):
    """research/assets/<id> as a symlink to a directory outside the vault:
    nothing there is removed or listed, and the link stays."""
    outside = tmp_path / "outside"
    files = [outside / "victim.txt", outside / "deep" / "victim2.txt"]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"keep")
    link = vault_with_notes / "research" / "assets" / "alpha-note"
    _symlink(link, outside)

    data = _rm("alpha-note")

    assert "removed_assets" not in data and "assets_not_removed" not in data
    assert all(path.read_bytes() == b"keep" for path in files)
    assert link.is_symlink()


def test_note_rm_keeps_the_directory_a_symlinked_assets_directory_points_to(vault_with_notes):
    """research/assets/<id> as a symlink to another note's directory. A file
    the note's own row names through the link goes, but the directory it
    sat in stays even once empty, and so does the link: neither is this
    note's to remove."""
    assets = vault_with_notes / "research" / "assets"
    target = assets / "beta-note"
    own = target / "own.png"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"o")
    link = assets / "alpha-note"
    _symlink(link, target)
    _row(vault_with_notes, "alpha-note", link / "own.png")

    data = _rm("alpha-note")

    assert data.get("removed_assets") == ["research/assets/beta-note/own.png"]
    assert "assets_not_removed" not in data
    assert not own.exists()
    assert target.is_dir() and link.is_symlink()


def test_note_rm_names_a_removed_symlink_by_its_own_path(vault_with_notes):
    """A symlink in the note's directory goes as a link: its target stays,
    and the payload names the link, not the target."""
    assets = vault_with_notes / "research" / "assets"
    target = assets / "beta-note" / "real.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"r")
    link = assets / "alpha-note" / "link.png"
    _symlink(link, target)

    data = _rm("alpha-note")

    assert data.get("removed_assets") == ["research/assets/alpha-note/link.png"]
    assert not link.is_symlink() and target.read_bytes() == b"r"


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="a read-only directory does not stop unlink here",
)
def test_note_rm_reports_a_file_it_cannot_remove_and_finishes_the_delete(vault_with_notes):
    """A file that cannot be unlinked (a viewer holding it open on Windows;
    a read-only directory stands in for that here) does not abort the
    delete: the note still goes, and the file is reported as not removed,
    never as removed."""
    locked = _asset(vault_with_notes, "alpha-note", "alpha-note/locked.png", b"l")
    os.chmod(locked.parent, 0o555)
    try:
        data = _rm("alpha-note")
    finally:
        os.chmod(locked.parent, 0o755)

    assert "removed_assets" not in data
    not_removed = data.get("assets_not_removed", [])
    assert len(not_removed) == 1
    assert not_removed[0].startswith("research/assets/alpha-note/locked.png: ")
    assert locked.read_bytes() == b"l"
    assert not (vault_with_notes / "research" / "notes" / "alpha-note.md").exists()
    vault = Vault(vault_with_notes)
    assert vault.db.execute("SELECT COUNT(*) FROM notes WHERE id = 'alpha-note'").fetchone()[0] == 0
    vault.close()


def test_note_rm_removes_symlinks_in_the_notes_directory_not_their_targets(
    vault_with_notes, tmp_path
):
    """A dangling link and a link to a file outside the vault, in the note's
    own directory: each link goes, as `shutil.rmtree` removed it, the target
    stays, and the emptied directory goes with them."""
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")
    assets_dir = vault_with_notes / "research" / "assets" / "alpha-note"
    assets_dir.mkdir(parents=True)
    _symlink(assets_dir / "dangling.png", tmp_path / "missing.png")
    _symlink(assets_dir / "outside.png", outside)

    data = _rm("alpha-note")

    assert sorted(data["removed_assets"]) == [
        "research/assets/alpha-note/dangling.png",
        "research/assets/alpha-note/outside.png",
    ]
    assert "assets_not_removed" not in data
    assert outside.read_bytes() == b"keep"
    assert not assets_dir.exists()


def test_note_rm_keeps_a_symlink_another_notes_row_names(vault_with_notes, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")
    assets_dir = vault_with_notes / "research" / "assets" / "alpha-note"
    assets_dir.mkdir(parents=True)
    link = assets_dir / "shared.png"
    _symlink(link, outside)
    _row(vault_with_notes, "beta-note", link)

    data = _rm("alpha-note")

    assert "removed_assets" not in data
    assert link.is_symlink()
