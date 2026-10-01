"""`hyperresearch install <path>` must not turn a missing path into a vault.

With no TTY (every agent session) install skips the setup TUI and falls through
to `Vault.init`, which creates parents. A stale or mistyped path then became a
new empty vault with exit 0, and the real vault kept its stale skills.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def test_install_refuses_a_missing_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "renamed-away" / "vault"

    result = runner.invoke(app, ["install", str(missing), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_code"] == "PATH_NOT_FOUND"
    assert "--create" in payload["error"]
    # The refusal is only worth anything if nothing was written.
    assert not missing.exists()
    assert not missing.parent.exists()


def test_install_refuses_a_missing_path_on_the_console(tmp_path: Path, monkeypatch):
    """The refusal is not a --json feature: the console branch exits 1 with the
    same message and writes nothing either."""
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "renamed-away"

    result = runner.invoke(app, ["install", str(missing)])

    assert result.exit_code == 1
    out = " ".join(result.output.split())
    assert "Error:" in out
    assert "does not exist" in out
    assert "--create" in out
    assert not missing.exists()


@pytest.mark.parametrize("name", ["[old] notes", "notes [/old]"], ids=["open-tag", "close-tag"])
def test_install_refusal_keeps_square_brackets_in_the_path(tmp_path: Path, monkeypatch, name):
    """The console line goes through Rich, which reads `[old]` in the path as
    markup and drops it from the message, and raises MarkupError on a `[/old]`
    that closes nothing, where the refusal should print."""
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / name

    result = runner.invoke(app, ["install", str(missing)])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    # The console folds a long path, so compare with all whitespace removed.
    out = "".join(result.output.split())
    assert "".join(str(Path(name)).split()) in out
    assert "doesnotexist" in out
    assert not missing.exists()


@pytest.mark.parametrize("extra", [[], ["--create"]], ids=["plain", "create"])
def test_install_refuses_a_path_that_is_a_file(tmp_path: Path, monkeypatch, extra):
    """A regular file is not a directory to install into, and --create cannot
    make it one. The refusal must be the structured kind, not a traceback from
    `mkdir(parents=True)` under the file."""
    monkeypatch.chdir(tmp_path)
    afile = tmp_path / "notes.md"
    afile.write_text("keep me", encoding="utf-8")

    result = runner.invoke(app, ["install", str(afile), *extra, "--json"])

    assert result.exit_code == 1
    assert result.output.startswith("{"), result.output
    payload = json.loads(result.output)
    assert payload["error_code"] == "NOT_A_DIRECTORY"
    assert "not a directory" in payload["error"]
    assert afile.read_text(encoding="utf-8") == "keep me"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.md"]


@pytest.mark.parametrize(
    "extra",
    [["--create"], ["--create", "--steps-only"], []],
    ids=["full", "steps-only", "plain"],
)
def test_install_refuses_a_file_as_a_parent(tmp_path: Path, monkeypatch, extra):
    """A file in the way of the path is refused with the same structured error,
    with `--create` and without it (where "pass --create" would be a false
    hint). The refusal is decided from the path, so no mkdir is attempted: the
    exception a mkdir under a file raises differs between platforms."""
    monkeypatch.chdir(tmp_path)
    afile = tmp_path / "notes.md"
    afile.write_text("keep me", encoding="utf-8")
    made: list[str] = []
    real_mkdir = os.mkdir

    def spy_mkdir(path, *args, **kwargs):
        made.append(os.fspath(path))
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", spy_mkdir)

    result = runner.invoke(app, ["install", str(afile / "sub"), *extra, "--json"])

    assert result.exit_code == 1
    assert result.output.startswith("{"), result.output
    payload = json.loads(result.output)
    assert payload["error_code"] == "NOT_A_DIRECTORY"
    assert "not a directory" in payload["error"]
    assert "--create" not in payload["error"]
    assert made == []
    assert afile.read_text(encoding="utf-8") == "keep me"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.md"]


def test_install_steps_only_refuses_a_missing_path(tmp_path: Path, monkeypatch):
    """Same shape on the bootstrap branch: it creates `.claude/skills` with
    parents, so a missing target became a directory holding only step skills."""
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "renamed-away"

    result = runner.invoke(app, ["install", str(missing), "--steps-only", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "PATH_NOT_FOUND"
    assert not missing.exists()


def test_install_create_flag_makes_the_directory(tmp_path: Path, monkeypatch):
    """Parents included: both levels are missing here."""
    monkeypatch.chdir(tmp_path)
    fresh = tmp_path / "new-parent" / "new-project"

    result = runner.invoke(app, ["install", str(fresh), "--create", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["vault"] == "created"
    assert (fresh / ".hyperresearch").is_dir()


def test_install_create_reports_any_other_mkdir_error(tmp_path: Path, monkeypatch):
    """A read-only parent, a full disk: whatever else the mkdir raises comes
    back in the envelope as CREATE_FAILED with the OS message, not as a
    traceback."""
    monkeypatch.chdir(tmp_path)
    fresh = tmp_path / "new-project"

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "mkdir", refuse)

    result = runner.invoke(app, ["install", str(fresh), "--create", "--json"])

    assert result.exit_code == 1
    assert result.output.startswith("{"), result.output
    payload = json.loads(result.output)
    assert payload["error_code"] == "CREATE_FAILED"
    assert "Permission denied" in payload["error"]
    assert not fresh.exists()


class _Terminal(io.StringIO):
    """Stdin that says it is a terminal, which is what routes a first-time
    install into the setup TUI."""

    def isatty(self) -> bool:
        return True


def test_install_refuses_a_missing_path_at_a_terminal(tmp_path: Path, monkeypatch, capsys):
    """The check comes before the route into the setup TUI, so a mistyped path
    is refused at a terminal too and the TUI, which would create it, never
    opens. Called directly: the test runner replaces stdin with one that is
    not a terminal."""
    from hyperresearch.cli.install import install

    monkeypatch.chdir(tmp_path)
    opened = []
    monkeypatch.setattr("hyperresearch.cli.setup.setup", lambda **kwargs: opened.append(kwargs))
    monkeypatch.setattr("sys.stdin", _Terminal())
    missing = tmp_path / "renamed-away"

    with pytest.raises(typer.Exit) as refused:
        install(
            path=str(missing),
            name="Research Base",
            json_output=False,
            global_install=False,
            steps_only=False,
            create=False,
            profile=None,
            target="claude",
        )

    assert refused.value.exit_code == 1
    assert opened == []
    assert "does not exist" in " ".join(capsys.readouterr().out.split())
    assert not missing.exists()


def test_install_in_an_existing_empty_directory_still_creates(tmp_path: Path, monkeypatch):
    """The documented first-time flow (`cd <new-project> && hyperresearch install .`)
    hands install a directory that exists and holds no vault. The guard is
    about the directory, not about `.hyperresearch/`, so this needs no flag."""
    fresh = tmp_path / "new-project"
    fresh.mkdir()
    monkeypatch.chdir(fresh)

    result = runner.invoke(app, ["install", ".", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["vault"] == "created"
    assert (fresh / ".hyperresearch").is_dir()


@pytest.mark.parametrize("args", [[], ["--json"]], ids=["no-tty", "json"])
def test_setup_without_a_terminal_still_makes_its_directory(tmp_path: Path, monkeypatch, args):
    """Interactive `setup <path>` creates the path, and without a terminal it
    hands off to install, so it passes --create rather than get a refusal
    that names an option `setup` does not have."""
    import subprocess

    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "call", lambda cmd: calls.append(cmd) or 0)
    target = str(tmp_path / "new-vault")

    result = runner.invoke(app, ["setup", target, *args], input="")

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][-len(args) - 3 :] == ["install", target, "--create", *args]
