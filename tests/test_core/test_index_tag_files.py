"""Each per-tag index page is one safe file, and index frontmatter is real YAML.

IndexGenerator named a tag's page `_tag-<tag>.md` with the tag text verbatim,
so a tag with a `/` (ci/cd, nested Obsidian tags) on 3+ notes pointed into a
subdirectory that does not exist: `index build` and `repair` crashed after
build_all had already deleted the old index pages. A tag too long for a
filename crashed the same way. The page id was the same raw text, which sync
re-slugifies, so `_tags.md` linked to an id no page had (`[[_tag-ci/cd]]`) and
tags that slugify alike (c, c++, c#) became an id collision. The frontmatter
was string-formatted into double-quoted YAML, so a tag with a `"` made the page
unparseable and every later sync reported it as an error.
"""

from __future__ import annotations

import json

import yaml
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.frontmatter import FRONTMATTER_RE
from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.indexgen.generator import IndexGenerator

runner = CliRunner()


def _sync(vault):
    return execute_sync(vault, compute_sync_plan(vault))


def _tag_notes(vault, *tags: str) -> None:
    """Three notes per tag: the threshold for a per-tag page."""
    for tag in tags:
        for i in range(3):
            write_note(vault.notes_dir, f"Tagged {i}", body=f"body {i}", tags=[tag])
    _sync(vault)


def _frontmatter(path) -> dict:
    return yaml.safe_load(FRONTMATTER_RE.match(path.read_text(encoding="utf-8")).group(1))


def _tag_pages(vault) -> dict:
    """Each per-tag page file, keyed by the tag its title names."""
    pages = {}
    for path in vault.index_dir.iterdir():
        if path.name.startswith("_tag-"):
            pages[_frontmatter(path)["title"].removeprefix("Tag: ")] = path
    return pages


def _assert_pages_indexed_and_linked(vault, pages: dict) -> None:
    """Every page is indexed under its file stem, and `_tags.md` links resolve to them."""
    for page in pages.values():
        row = vault.db.execute(
            "SELECT id FROM notes WHERE path = ?", (f"research/index/{page.name}",)
        ).fetchone()
        assert row is not None, page.name
        assert row["id"] == page.stem
    links = vault.db.execute(
        "SELECT target_ref, target_id FROM links WHERE source_id = '_tags'"
    ).fetchall()
    assert {(link["target_ref"], link["target_id"]) for link in links} == {
        (page.stem, page.stem) for page in pages.values()
    }


def test_a_tag_with_a_slash_gets_one_page_file(tmp_vault):
    _tag_notes(tmp_vault, "ci/cd")

    built = IndexGenerator(tmp_vault).build_all()

    pages = _tag_pages(tmp_vault)
    assert set(pages) == {"ci/cd"}
    assert pages["ci/cd"].parent == tmp_vault.index_dir
    assert f"index/{pages['ci/cd'].name}" in built
    # The pages after the tag pages are rebuilt too, not only the two before them.
    assert (tmp_vault.index_dir / "_most-linked.md").exists()

    assert _sync(tmp_vault).errors == []
    _assert_pages_indexed_and_linked(tmp_vault, pages)


def test_a_tag_with_a_double_quote_writes_valid_frontmatter(tmp_vault):
    _tag_notes(tmp_vault, 'say "hi"')

    IndexGenerator(tmp_vault).build_all()

    page = next(tmp_vault.index_dir.glob("_tag-*.md"))
    meta = _frontmatter(page)
    assert meta["title"] == 'Tag: say "hi"'
    assert meta["id"] == page.stem
    assert meta["type"] == "index"
    assert _sync(tmp_vault).errors == []


def test_tags_index_links_reach_every_tag_page(tmp_vault):
    tags = {"ci/cd", "machine learning", 'say "hi"', "web3.0", "python"}
    _tag_notes(tmp_vault, *tags)

    IndexGenerator(tmp_vault).build_all()

    assert _sync(tmp_vault).errors == []
    pages = _tag_pages(tmp_vault)
    assert set(pages) == tags
    _assert_pages_indexed_and_linked(tmp_vault, pages)


def test_ordinary_tags_keep_their_page_filenames(tmp_vault):
    _tag_notes(tmp_vault, "python", "machine-learning", "deep_learning", "llm2")

    IndexGenerator(tmp_vault).build_all()

    assert {p.name for p in tmp_vault.index_dir.glob("_tag-*.md")} == {
        "_tag-python.md",
        "_tag-machine-learning.md",
        "_tag-deep_learning.md",
        "_tag-llm2.md",
    }


def test_tags_that_slugify_alike_get_distinct_pages(tmp_vault):
    _tag_notes(tmp_vault, "c", "c++", "c#")

    IndexGenerator(tmp_vault).build_all()

    assert _sync(tmp_vault).errors == []
    pages = _tag_pages(tmp_vault)
    assert set(pages) == {"c", "c++", "c#"}
    assert pages["c"].name == "_tag-c.md"
    _assert_pages_indexed_and_linked(tmp_vault, pages)

    # A rebuild names every page the same way again.
    names = {tag: page.name for tag, page in pages.items()}
    IndexGenerator(tmp_vault).build_all()
    assert {tag: page.name for tag, page in _tag_pages(tmp_vault).items()} == names


def test_long_tags_get_distinct_pages_with_short_names(tmp_vault):
    first, second = "x" * 299 + "a", "x" * 299 + "b"
    _tag_notes(tmp_vault, first, second)

    IndexGenerator(tmp_vault).build_all()

    assert _sync(tmp_vault).errors == []
    pages = _tag_pages(tmp_vault)
    assert set(pages) == {first, second}
    assert all(len(page.name.encode("utf-8")) <= 255 for page in pages.values())
    _assert_pages_indexed_and_linked(tmp_vault, pages)


def test_index_build_and_repair_succeed_with_a_slash_tag(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    for i in range(3):
        result = runner.invoke(app, ["note", "new", f"Pipeline {i}", "-t", "ci/cd", "-b", f"body {i}"])
        assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["index", "build", "-j"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert any(p.startswith("index/_tag-") for p in payload["data"]["built"])

    result = runner.invoke(app, ["repair", "-j"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    # `_tags.md` links to the ci/cd page, so a wrong link target shows up here.
    assert payload["data"]["health"]["broken_links"] == 0
