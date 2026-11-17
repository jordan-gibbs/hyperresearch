"""Every tag with a per-tag index page gets a page file of its own.

A tag that shares its slug with other tags gets a digest name,
`_tag-<digest>-<tag>`, and _tag_page_ids checked that name only against the
other tags in the same slug group. A digest name is an ordinary slug, so a tag
anywhere else in the vault could already own it. With c, c++ and cedb1bac-c on
3 notes each, c++ was named `_tag-cedb1bac-c` (cedb1bac starts its sha256),
which is also the name of the tag cedb1bac-c. One page overwrote the other and
`_tags.md` sent both tags to the page that was left. Two tags in one group
whose digests start alike collided the same way. So did two names that differ
only in case beyond what lower() folds (the micro sign and Greek mu), because
macOS and Windows treat them as one file.
"""

from __future__ import annotations

import hashlib
import random
import re

import pytest
import yaml

from hyperresearch.core.frontmatter import FRONTMATTER_RE
from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.indexgen.generator import IndexGenerator
from hyperresearch.models.note import slugify

# A `_tags.md` line for a tag with a page: `- **<tag>** (<n> notes) → [[<id>]]`.
_TAGS_INDEX_LINK = re.compile(r"^- \*\*(.+)\*\* \(\d+ notes\) → \[\[(.+)\]\]$", re.MULTILINE)


def _sync(vault):
    return execute_sync(vault, compute_sync_plan(vault))


def _tag_notes(vault, tags, label: str = "seed") -> None:
    """Three notes that each carry every tag: the threshold for a per-tag page."""
    for i in range(3):
        write_note(vault.notes_dir, f"Tagged {label} {i}", body=f"body {i}", tags=sorted(tags))
    _sync(vault)


def _frontmatter(path) -> dict:
    return yaml.safe_load(FRONTMATTER_RE.match(path.read_text(encoding="utf-8")).group(1))


def _build_and_check(vault, tags) -> dict[str, str]:
    """Build the index, assert every tag got a page of its own, and map tag to page id."""
    IndexGenerator(vault).build_all()
    assert _sync(vault).errors == []

    files = list(vault.index_dir.glob("_tag-*.md"))
    page_ids = {_frontmatter(path)["title"].removeprefix("Tag: "): path.stem for path in files}
    # One file per tag, so no tag's page was overwritten by another's.
    assert len(files) == len(tags)
    assert set(page_ids) == set(tags)
    # Nor would one be on macOS or Windows, where names that differ only in
    # case are one file. On a filesystem that keeps them apart, such as
    # Linux's, only this check catches that.
    assert len({page_id.upper() for page_id in page_ids.values()}) == len(tags)
    # `_tags.md` sends each tag to its own page, and that page is indexed under
    # the same id, so the link resolves to it.
    tags_index = (vault.index_dir / "_tags.md").read_text(encoding="utf-8")
    assert dict(_TAGS_INDEX_LINK.findall(tags_index)) == page_ids
    for tag, page_id in page_ids.items():
        row = vault.db.execute(
            "SELECT id FROM notes WHERE path = ?", (f"research/index/{page_id}.md",)
        ).fetchone()
        assert row is not None and row["id"] == page_id, tag
    # A tag whose `_tag-<tag>` is already a slug keeps that name, unless that
    # name is the same file as another such tag's.
    own_names = [f"_tag-{tag}" for tag in tags if slugify(f"_tag-{tag}") == f"_tag-{tag}"]
    for name in own_names:
        if [other.upper() for other in own_names].count(name.upper()) == 1:
            assert page_ids[name.removeprefix("_tag-")] == name
    return page_ids


def _digest8(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()[:8]


def test_a_digest_name_owned_by_another_tag_goes_to_that_tag(tmp_vault):
    # The reviewers' example. c++ shares c's slug, and its first-choice name,
    # `_tag-cedb1bac-c`, is the name of the tag cedb1bac-c.
    assert _digest8("c++") == "cedb1bac"
    tags = {"c", "c++", "cedb1bac-c"}
    _tag_notes(tmp_vault, tags)

    page_ids = _build_and_check(tmp_vault, tags)

    assert page_ids["c"] == "_tag-c"
    assert page_ids["cedb1bac-c"] == "_tag-cedb1bac-c"


def test_tags_whose_digests_start_alike_get_distinct_pages(tmp_vault):
    # Found by search: both slugify to `_tag-c` and their digests share the
    # first 8 hex digits, so both first try `_tag-aa56a652-c`.
    first, second = "c##%^+", "c!$*&#"
    assert slugify(f"_tag-{first}") == slugify(f"_tag-{second}") == "_tag-c"
    assert _digest8(first) == _digest8(second)
    tags = {"c", first, second}
    _tag_notes(tmp_vault, tags)

    page_ids = _build_and_check(tmp_vault, tags)

    # A rebuild names every page the same way again.
    assert _build_and_check(tmp_vault, tags) == page_ids


def test_tags_whose_names_are_one_file_without_case_get_distinct_pages(tmp_vault):
    # Each pair is two lowercase tags, and two slugs, that macOS or Windows
    # treat as one file name: the micro sign and Greek mu, final and medial
    # sigma, and (on Windows) dotless and dotted i. Before the fix the second
    # page of each pair overwrote the first there.
    micro, mu = "\u00b5m", "\u03bcm"
    final_sigma, sigma = "\u03bb\u03bf\u03b3\u03bf\u03c2", "\u03bb\u03bf\u03b3\u03bf\u03c3"
    dotless, dotted = "k\u0131r", "kir"
    # `_tag-<micro>g` is only the slug of micro_g_plus, which sorts first but
    # must not take the name from mu_g, whose `_tag-<tag>` already is a slug.
    micro_g_plus, mu_g = "\u00b5g+", "\u03bcg"
    tags = {micro, mu, final_sigma, sigma, dotless, dotted, micro_g_plus, mu_g}
    _tag_notes(tmp_vault, tags)

    page_ids = _build_and_check(tmp_vault, tags)

    # Of two such tags, the one that sorts first keeps its name and the other
    # gets a digest name.
    assert page_ids[micro] == f"_tag-{micro}"
    assert page_ids[final_sigma] == f"_tag-{final_sigma}"
    assert page_ids[dotted] == "_tag-kir"
    assert page_ids[mu_g] == f"_tag-{mu_g}"
    for tag in (mu, sigma, dotless, micro_g_plus):
        assert page_ids[tag].startswith(f"_tag-{_digest8(tag)}-")
    assert _build_and_check(tmp_vault, tags) == page_ids


def _random_tags(seed: int) -> set[str]:
    """Short tags over an alphabet where many of them slugify alike."""
    rng = random.Random(seed)
    tags: set[str] = set()
    while len(tags) < 12:
        tag = "".join(rng.choice("c+# -_x") for _ in range(rng.randint(1, 4))).strip()
        if tag:
            tags.add(tag)
    return tags


@pytest.mark.parametrize(
    "seed_tags",
    [
        {"c", "c++", "c#"},
        # Long enough that slugify caps every name these tags are given.
        {"x" * 299 + "a", "x" * 299 + "b"},
        _random_tags(0),
        _random_tags(1),
        _random_tags(2),
    ],
    ids=["c-family", "capped", "random-0", "random-1", "random-2"],
)
def test_tags_named_after_other_tags_pages_never_share_one(tmp_vault, seed_tags):
    # Each round claims the page name of every tag that got a digest name, by
    # adding a tag spelled like that name, and checks the vault again.
    tags = set(seed_tags)
    _tag_notes(tmp_vault, tags)
    for round_ in range(4):
        page_ids = _build_and_check(tmp_vault, tags)
        claimed = {
            page_id.removeprefix("_tag-")
            for tag, page_id in page_ids.items()
            if page_id != f"_tag-{tag}" and page_id.startswith("_tag-")
        }
        assert claimed, "every tag already has its own name; nothing left to claim"
        tags |= claimed
        _tag_notes(tmp_vault, claimed, f"round {round_}")
    _build_and_check(tmp_vault, tags)
