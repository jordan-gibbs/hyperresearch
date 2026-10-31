"""A failed copy leaves no partial note, and import counts only what indexed.

import and note creation open the file exclusively and then write it, so a
write that failed partway (a full disk, Ctrl-C) left the truncated file in
place. import skips a destination that exists, so every retry skipped it and
the truncation was permanent; a later note new under the same name moved to
<id>-2.md and left the partial file in the vault.

import also took any notes row at a copy's path as proof that the copy
indexed. A row left by a file removed without a sync sits at that path, so a
copy sync refused (an id collision, a frontmatter that does not parse) was
reported as imported while the index still held the old note's body.
"""

# The file is named for its review unit (import-robust); pytest imports it by
# path, so the hyphen in the module name is harmless.

from __future__ import annotations

import errno
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import create_note_file, read_note, write_note
from hyperresearch.core.vault import Vault

runner = CliRunner()

NOTE = "---\ntitle: Big\nid: big\n---\n\n" + "complete body line\n" * 20


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    vault_dir = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(vault_dir)]).exit_code == 0
    monkeypatch.chdir(vault_dir)
    return vault_dir


def _import(*args: str):
    result = runner.invoke(app, ["import", *args, "--json"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    return result, json.loads(result.output)


def _sync() -> None:
    assert runner.invoke(app, ["sync"]).exit_code == 0


def _body_at(vault_dir: Path, rel: str) -> str:
    row = Vault.discover(vault_dir).db.execute(
        "SELECT c.body FROM notes n JOIN note_content c ON c.note_id = n.id WHERE n.path = ?",
        (rel,),
    ).fetchone()
    return row["body"]


def _full_disk() -> OSError:
    return OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))


def _copy_then_fail(exc: BaseException):
    """A copyfileobj that writes 40 bytes and then raises `exc`, once."""
    real = shutil.copyfileobj
    calls = []

    def copyfileobj(fsrc, fdst, *args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            return real(fsrc, fdst, *args, **kwargs)
        fdst.write(fsrc.read(40))
        fdst.flush()
        raise exc

    return "copyfileobj", copyfileobj


def _copystat_fails():
    real = shutil.copystat
    calls = []

    def copystat(src, dst, *args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            return real(src, dst, *args, **kwargs)
        raise PermissionError(errno.EPERM, "Operation not permitted")

    return "copystat", copystat


@pytest.mark.parametrize(
    "inject",
    [
        lambda: _copy_then_fail(_full_disk()),
        lambda: _copy_then_fail(KeyboardInterrupt()),
        _copystat_fails,
    ],
    ids=["disk-full-mid-copy", "interrupted-mid-copy", "copystat-fails"],
)
def test_an_import_that_fails_mid_copy_leaves_no_file_and_a_retry_imports_it(
    vault_dir: Path, tmp_path: Path, monkeypatch, inject
):
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.md").write_text(NOTE, encoding="utf-8")
    dest = vault_dir / "research" / "notes" / "big.md"
    name, failing = inject()
    monkeypatch.setattr(shutil, name, failing)

    failed = runner.invoke(app, ["import", str(src), "--json"])

    assert failed.exit_code != 0
    assert not dest.exists() and not dest.is_symlink()

    result, payload = _import(str(src))

    assert result.exit_code == 0, result.output
    assert payload["data"]["imported"] == [{"source": "big.md", "destination": "big.md"}]
    assert payload["data"]["skipped"] == []
    assert dest.read_bytes() == (src / "big.md").read_bytes()
    assert "complete body line" in _body_at(vault_dir, "research/notes/big.md")


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="a mode without owner read does not stop reading here",
)
def test_a_copy_its_owner_cannot_read_does_not_abort_the_import(
    vault_dir: Path, tmp_path: Path, monkeypatch
):
    """copystat gives the copy the source's mode bits but not the ACL or
    group that let this user read the source, so the copy can come out
    unreadable. Hashing it then raised and aborted the whole import; it is
    reported and the rest is imported."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "acl.md").write_text("---\ntitle: Acl\nid: acl\n---\n\nacl body\n", encoding="utf-8")
    (src / "zed.md").write_text("---\ntitle: Zed\nid: zed\n---\n\nzed\n", encoding="utf-8")
    dest = vault_dir / "research" / "notes" / "acl.md"
    real = shutil.copystat

    def copystat(src, dst, *args, **kwargs):
        real(src, dst, *args, **kwargs)
        if Path(dst).name == "acl.md":
            os.chmod(dst, 0)  # the mode of a source shared through an ACL

    monkeypatch.setattr(shutil, "copystat", copystat)
    try:
        result, payload = _import(str(src))
    finally:
        if dest.exists():
            os.chmod(dest, 0o644)

    assert result.exit_code == 0, result.output
    data = payload["data"]
    assert data["imported"] == [{"source": "zed.md", "destination": "zed.md"}]
    assert [(i["source"], i["error_code"]) for i in data["not_indexed"]] == [
        ("acl.md", "NOTE_NOT_INDEXED")
    ]
    assert dest.read_bytes() == (src / "acl.md").read_bytes()


def test_a_failed_copy_never_removes_a_note_it_did_not_create(
    vault_dir: Path, tmp_path: Path, monkeypatch
):
    """The destination is taken, so the copy never starts; whatever fails
    later must not take that note with it."""
    note = vault_dir / "research" / "notes" / "big.md"
    note.write_text("---\ntitle: Mine\n---\nmine\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.md").write_text(NOTE, encoding="utf-8")
    monkeypatch.setattr(shutil, *_copy_then_fail(_full_disk()))

    result, payload = _import(str(src))

    assert result.exit_code == 0, result.output
    assert [s["error_code"] for s in payload["data"]["skipped"]] == ["DESTINATION_EXISTS"]
    assert note.read_text(encoding="utf-8") == "---\ntitle: Mine\n---\nmine\n"


class _FailsMidWrite:
    """A text file that takes half of a write, then reports a full disk."""

    def __init__(self, f) -> None:
        self._f = f

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self._f.close()

    def write(self, text: str) -> int:
        self._f.write(text[: len(text) // 2])
        self._f.flush()
        raise _full_disk()


def test_create_note_file_that_fails_mid_write_leaves_no_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "note.md"
    content = "---\ntitle: Note\n---\n\n" + "a sentence of the body\n" * 20
    real_open = Path.open

    def open_failing(self, mode="r", *args, **kwargs):
        f = real_open(self, mode, *args, **kwargs)
        return _FailsMidWrite(f) if "x" in mode else f

    monkeypatch.setattr(Path, "open", open_failing)
    with pytest.raises(OSError, match=os.strerror(errno.ENOSPC)):
        create_note_file(path, content)
    assert not path.exists()

    monkeypatch.setattr(Path, "open", real_open)
    assert create_note_file(path, content) is True
    assert path.read_text(encoding="utf-8") == content


def test_create_note_file_never_removes_a_file_it_did_not_create(tmp_path: Path):
    path = tmp_path / "note.md"
    path.write_text("someone else's note", encoding="utf-8")

    assert create_note_file(path, "mine") is False
    assert path.read_text(encoding="utf-8") == "someone else's note"


def test_a_note_whose_body_cannot_be_written_does_not_take_its_name(tmp_vault):
    """A lone surrogate (from JSON's \\udXXX escapes, or argv bytes that are
    not UTF-8) fails the encode inside the write. The empty file it left
    held the name, so the retry wrote title-2.md under id title-2."""
    with pytest.raises(UnicodeEncodeError):
        write_note(tmp_vault.notes_dir, "Title", body="broken \udcff byte")
    assert list(tmp_vault.notes_dir.iterdir()) == []

    path = write_note(tmp_vault.notes_dir, "Title", body="fixed")

    assert path.name == "title.md"
    assert read_note(path, tmp_vault.root).meta.id == "title"


def _stale_row_at_foo(vault_dir: Path) -> None:
    """Index foo.md and bar.md, then remove foo.md without a sync: the row
    for foo.md stays at research/notes/foo.md."""
    notes = vault_dir / "research" / "notes"
    (notes / "foo.md").write_text("---\ntitle: Foo\nid: foo\n---\n\nOLD FOO BODY\n", encoding="utf-8")
    (notes / "bar.md").write_text("---\ntitle: Bar\nid: bar\n---\n\nbar\n", encoding="utf-8")
    _sync()
    (notes / "foo.md").unlink()


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("---\ntitle: Imposter\nid: bar\n---\n\nNEW BODY\n", "id collision"),
        ("---\ntitle: [unclosed\nid: foo\n---\n\nNEW BODY\n", "while parsing"),
    ],
    ids=["id-collision", "frontmatter-does-not-parse"],
)
def test_import_over_a_stale_row_counts_a_refused_copy_as_not_indexed(
    vault_dir: Path, tmp_path: Path, content: str, reason: str
):
    _stale_row_at_foo(vault_dir)
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.md").write_text(content, encoding="utf-8")

    result, payload = _import(str(src))

    assert result.exit_code == 0, result.output
    data = payload["data"]
    assert data["imported"] == []
    assert data["count"] == payload["count"] == 0
    [not_indexed] = data["not_indexed"]
    assert not_indexed["source"] == "foo.md"
    assert not_indexed["error_code"] == "NOTE_NOT_INDEXED"
    assert reason in not_indexed["error"]
    assert "OLD FOO BODY" in _body_at(vault_dir, "research/notes/foo.md")


def test_import_over_a_stale_row_with_no_sync_error_still_checks_the_content(
    vault_dir: Path, tmp_path: Path
):
    """Sync takes a file whose mtime matches its row as unchanged without
    reading it. copy2 keeps the source's mtime, so a copy whose source has
    the removed file's mtime is never indexed, and sync reports no error."""
    _stale_row_at_foo(vault_dir)
    mtime = Vault.discover(vault_dir).db.execute(
        "SELECT file_mtime FROM notes WHERE path = 'research/notes/foo.md'"
    ).fetchone()["file_mtime"]
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.md").write_text("---\ntitle: Foo\nid: foo\n---\n\nNEW BODY\n", encoding="utf-8")
    os.utime(src / "foo.md", (mtime, mtime))

    result, payload = _import(str(src))

    assert result.exit_code == 0, result.output
    data = payload["data"]
    assert data["imported"] == []
    assert data["count"] == 0
    [not_indexed] = data["not_indexed"]
    assert not_indexed["error_code"] == "NOTE_NOT_INDEXED"
    assert "different content" in not_indexed["error"]
    assert "OLD FOO BODY" in _body_at(vault_dir, "research/notes/foo.md")


def test_import_over_a_stale_row_counts_a_copy_that_indexed(vault_dir: Path, tmp_path: Path):
    _stale_row_at_foo(vault_dir)
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.md").write_text("---\ntitle: Foo\nid: foo\n---\n\nNEW BODY\n", encoding="utf-8")

    result, payload = _import(str(src))

    assert result.exit_code == 0, result.output
    assert payload["data"]["imported"] == [{"source": "foo.md", "destination": "foo.md"}]
    assert payload["data"]["not_indexed"] == []
    assert "NEW BODY" in _body_at(vault_dir, "research/notes/foo.md")
