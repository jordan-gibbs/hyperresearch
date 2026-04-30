from __future__ import annotations

import json
from pathlib import Path

from hyperresearch.core.opencode_models import resolve_opencode_model_choices


def test_opencode_model_resolver_prefers_flat_rate_equivalent(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "opencode"
    config_dir.mkdir()
    (config_dir / "opencode.json").write_text(
        json.dumps(
            {
                "model": "anthropic/claude-sonnet-4-5",
                "agent": {
                    "build": {"model": "opencode-go/claude-sonnet-4-5"},
                    "review": {"model": "anthropic/claude-opus-4-1"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HYPERRESEARCH_OPENCODE_CONFIG_DIR", str(config_dir))

    choices = resolve_opencode_model_choices(tmp_path)

    assert choices["sonnet"].model == "opencode-go/claude-sonnet-4-5"
    assert choices["opus"].model == "anthropic/claude-opus-4-1"


def test_opencode_model_resolver_uses_active_non_claude_roles(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "opencode"
    config_dir.mkdir()
    (config_dir / "oh-my-openagent.json").write_text(
        json.dumps(
            {
                "agents": {
                    "oracle": {"model": "openai/gpt-5.5", "variant": "xhigh"},
                    "sisyphus": {"model": "opencode-go/kimi-k2.6"},
                    "librarian": {
                        "model": "opencode-go/minimax-m2.7",
                        "fallback_models": [
                            {"model": "opencode-go/minimax-m2.7-highspeed"},
                            {"model": "openai/gpt-5.4-nano"},
                        ],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HYPERRESEARCH_OPENCODE_CONFIG_DIR", str(config_dir))

    choices = resolve_opencode_model_choices(tmp_path)

    assert choices["opus"].model == "openai/gpt-5.5"
    assert choices["opus"].variant == "xhigh"
    assert choices["sonnet"].model == "opencode-go/kimi-k2.6"
    assert choices["haiku"].model == "opencode-go/minimax-m2.7-highspeed"


def test_opencode_model_resolver_falls_back_without_active_models(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "empty-opencode"
    config_dir.mkdir()
    monkeypatch.setenv("HYPERRESEARCH_OPENCODE_CONFIG_DIR", str(config_dir))

    choices = resolve_opencode_model_choices(tmp_path)

    assert choices["opus"].model.startswith("anthropic/claude-opus")
    assert choices["sonnet"].model.startswith("anthropic/claude-sonnet")
    assert choices["haiku"].model.startswith("anthropic/claude-haiku")
