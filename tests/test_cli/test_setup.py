from __future__ import annotations

from hyperresearch.cli import setup as setup_cli


def test_choose_platforms_interactive_uses_checklist(monkeypatch):
    monkeypatch.setattr(setup_cli, "_run_platform_checklist", lambda: {"claude"})

    assert setup_cli.choose_platforms_interactive() == {"claude"}


def test_choose_platforms_interactive_falls_back_when_checklist_unavailable(monkeypatch):
    answers = iter([False, False, False, True])

    def fail_checklist():
        raise RuntimeError("no curses")

    monkeypatch.setattr(setup_cli, "_run_platform_checklist", fail_checklist)
    monkeypatch.setattr(setup_cli.Confirm, "ask", lambda *args, **kwargs: next(answers))

    assert setup_cli.choose_platforms_interactive() == {"opencode"}
