"""Two writers creating a note under the same name must both keep their note.

write_note checked `file_path.exists()` and then called `write_text()`, so two
processes creating a note with the same title (parallel fetchers in step 2, two
MCP servers on one vault, parallel `note new`) both saw the name free, both
wrote it, and the last write replaced the first. Every caller reported success,
the fetch paths recorded several URLs against the one surviving note, and the
lost bodies were gone for good. A create now opens the file exclusively and
moves to the next free name when another writer got there first.

compute_sync_plan also listed a file and then stat()ed it; a file removed in
between (a fetch that lost a race cleans up its note) crashed the whole sync
with FileNotFoundError.
"""

from __future__ import annotations

import json
import multiprocessing
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import read_note, write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync

runner = CliRunner()


def _bodies(paths: list[Path], vault_root: Path) -> set[str]:
    return {read_note(p, vault_root).body.strip() for p in paths}


def test_two_writers_choosing_the_same_name_both_keep_their_note(tmp_vault, monkeypatch):
    """Both writers settle on `race.md` before either has written it: the
    window the old exists()-then-write loop left open. Holding each writer's
    first render at a barrier forces that interleaving every run."""
    import hyperresearch.core.note as note_mod

    real_render = note_mod.render_note
    barrier = threading.Barrier(2, timeout=10)
    first_render = threading.local()

    def render_in_lockstep(meta, body):
        if not getattr(first_render, "done", False):
            first_render.done = True
            barrier.wait()
        return real_render(meta, body)

    monkeypatch.setattr(note_mod, "render_note", render_in_lockstep)

    paths: dict[int, Path] = {}
    errors: list[BaseException] = []

    def writer(i: int) -> None:
        try:
            paths[i] = write_note(tmp_vault.notes_dir, "Race", body=f"writer {i}")
        except BaseException as exc:  # surfaced below; a thread swallows it otherwise
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert paths[0] != paths[1]
    assert sorted(p.name for p in tmp_vault.notes_dir.glob("*.md")) == ["race-2.md", "race.md"]
    assert _bodies(list(paths.values()), tmp_vault.root) == {"writer 0", "writer 1"}
    for p in paths.values():
        assert read_note(p, tmp_vault.root).meta.id == p.stem

    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert result.errors == []
    assert result.added == 2


def _write_after_barrier(notes_dir: str, i: int, barrier, out) -> None:
    barrier.wait()
    out.put((i, str(write_note(Path(notes_dir), "Race", body=f"writer {i}"))))


def test_parallel_processes_writing_the_same_title_lose_nothing(tmp_vault):
    """Real processes released together, as parallel fetchers are."""
    n = 6
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(n, timeout=30)
    out = ctx.Queue()
    procs = [
        ctx.Process(target=_write_after_barrier, args=(str(tmp_vault.notes_dir), i, barrier, out))
        for i in range(n)
    ]
    for p in procs:
        p.start()
    results = [out.get(timeout=30) for _ in range(n)]
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    paths = [Path(path) for _, path in results]
    assert len(set(paths)) == n
    assert len(list(tmp_vault.notes_dir.glob("*.md"))) == n
    assert _bodies(paths, tmp_vault.root) == {f"writer {i}" for i in range(n)}


def test_note_new_template_never_overwrites_a_file_that_appeared_after_its_check(
    tmp_vault, monkeypatch
):
    """`note new --template` writes its own file. A rival written after the
    name was found free (simulated by an exists() that answers for the moment
    before the rival appeared) must survive, and the new note goes elsewhere."""
    monkeypatch.chdir(tmp_vault.root)
    notes_dir = tmp_vault.notes_dir
    rival = notes_dir / "foo.md"
    rival.write_text("---\ntitle: Rival\nid: foo\n---\n\nRival body.\n", encoding="utf-8")

    real_exists = Path.exists

    def exists_before_the_rival(self, *args, **kwargs):
        if self.parent == notes_dir and self.suffix == ".md":
            return False
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists_before_the_rival)
    result = runner.invoke(app, ["note", "new", "Foo", "--template", "concept", "--json"])
    monkeypatch.setattr(Path, "exists", real_exists)

    assert result.exit_code == 0, result.output
    assert rival.read_text(encoding="utf-8").endswith("Rival body.\n")
    written = tmp_vault.root / json.loads(result.stdout)["data"]["path"]
    assert written != rival
    assert written.read_text(encoding="utf-8").startswith("---\n")


@pytest.mark.parametrize("indexed", [False, True], ids=["new-file", "indexed-file"])
def test_compute_sync_plan_skips_a_file_removed_after_listing(tmp_vault, monkeypatch, indexed):
    """A file can vanish between the directory listing and its stat(); the
    plan skips it (an indexed one becomes a delete) instead of crashing."""
    import hyperresearch.core.sync as sync_mod

    write_note(tmp_vault.notes_dir, "Keeper", body="stays")
    gone = write_note(tmp_vault.notes_dir, "Gone", body="removed mid-scan")
    if indexed:
        execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    real_probe = sync_mod._has_frontmatter

    def probe_then_remove(path: Path) -> bool:
        has = real_probe(path)
        if path == gone:
            path.unlink()
        return has

    monkeypatch.setattr(sync_mod, "_has_frontmatter", probe_then_remove)
    plan = compute_sync_plan(tmp_vault)

    assert gone not in plan.to_add
    assert gone not in plan.to_update
    gone_rel = gone.relative_to(tmp_vault.root).as_posix()
    if indexed:
        assert plan.to_delete == [gone_rel]
        assert plan.unchanged == 1
    else:
        assert [p.name for p in plan.to_add] == ["keeper.md"]
        assert plan.to_delete == []
