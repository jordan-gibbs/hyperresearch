"""A run tag is a slug; it can only ever name a child of research/runs/ (#116).

`Vault.run_dir()` joins the tag onto research/runs/ and pathlib replaces the
base on an absolute segment, so before this `run init ../../x` (or an
absolute path) scaffolded a run workspace outside the vault and every later
`run` subcommand followed it there. Same bug class as the `claims ingest
--tag` traversal fixed in #114; this one is closed at the single seam every
run command goes through.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.vault import InvalidRunTagError, validate_run_tag

runner = CliRunner()


@pytest.mark.parametrize(
    "tag",
    [
        "efield-dft-sac-3f9a1c",
        "non-ai-web-design-trends-2026-b0dbbe",
        "Run_2026.09.12",
        "a",
        "x" * 100,
    ],
)
def test_slugs_pass(tag):
    assert validate_run_tag(tag) == tag


@pytest.mark.parametrize(
    "tag",
    [
        "../../x",
        "..",
        ".",
        ".hidden",
        "-leading-dash",
        "a/b",
        "a\b",
        "C:/anything",
        "/etc/passwd",
        "has space",
        "",
        "x" * 101,
        "tag\n",
    ],
)
def test_paths_and_junk_are_refused(tag):
    with pytest.raises(InvalidRunTagError):
        validate_run_tag(tag)


def test_run_dir_refuses_before_touching_the_filesystem(tmp_vault):
    with pytest.raises(InvalidRunTagError):
        tmp_vault.run_dir("../../escape")
    assert not (tmp_vault.root.parent / "escape").exists()


def test_run_init_with_a_traversal_tag_is_a_clean_error(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    outside = tmp_vault.root.parent / "outside"

    result = runner.invoke(app, ["run", "init", "../../outside", "-j"])

    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["ok"] is False
    assert "invalid run tag" in payload["error"]
    assert not outside.exists()
    assert not (tmp_vault.root / "research" / "runs").exists() or not any(
        (tmp_vault.root / "research" / "runs").iterdir()
    )


def test_run_init_with_an_absolute_tag_is_a_clean_error(tmp_vault, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    target = tmp_path / "elsewhere"

    result = runner.invoke(app, ["run", "init", str(target), "-j"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not target.exists()


def test_other_run_commands_report_the_bad_tag_too(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    for argv in (
        ["run", "status", "../../x", "-j"],
        ["run", "step", "../../x", "1", "--status", "done", "-j"],
        ["run", "verify", "../../x", "-j"],
        ["citecheck", "extract", "../../x", "-j"],
        ["levers", "render", "../../x", "-j"],
    ):
        result = runner.invoke(app, argv)
        assert result.exit_code == 1, argv
        assert json.loads(result.stdout)["ok"] is False, argv
        assert "invalid run tag" in json.loads(result.stdout)["error"], argv


def test_a_good_tag_still_scaffolds_inside_the_vault(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)

    result = runner.invoke(app, ["run", "init", "good-tag-0a1b2c", "-j"])

    assert result.exit_code == 0, result.stdout
    assert (tmp_vault.root / "research" / "runs" / "good-tag-0a1b2c" / "run.json").exists()
