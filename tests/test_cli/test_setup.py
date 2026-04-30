from __future__ import annotations

from hyperresearch.cli import setup as setup_cli


def test_choose_platforms_interactive_uses_yes_no_selection(monkeypatch):
    answers = iter([True, False])

    monkeypatch.setattr(setup_cli.Confirm, "ask", lambda *args, **kwargs: next(answers))

    assert setup_cli.choose_platforms_interactive() == {"claude"}


def test_choose_platforms_interactive_requires_at_least_one(monkeypatch):
    answers = iter([False, False, False, True])

    monkeypatch.setattr(setup_cli.Confirm, "ask", lambda *args, **kwargs: next(answers))

    assert setup_cli.choose_platforms_interactive() == {"opencode"}
