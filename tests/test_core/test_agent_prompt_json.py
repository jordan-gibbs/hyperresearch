"""Check the installed agent contracts, including the Codex TOML translation."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from hyperresearch.core.hooks import install_hooks


@pytest.fixture(params=["claude", "codex"])
def installed_agents(tmp_path: Path, request) -> dict[str, str]:
    platform = request.param
    install_hooks(tmp_path, hpr_path="hyperresearch", platform=platform)
    agents_dir = tmp_path / f".{platform}" / "agents"
    suffix = ".md" if platform == "claude" else ".toml"
    paths = sorted(agents_dir.glob(f"*{suffix}"))
    # Codex omits the browser fetcher, which requires Claude-in-Chrome.
    assert len(paths) == (16 if platform == "claude" else 15)
    agents = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        agents[path.name] = (
            text if platform == "claude" else tomllib.loads(text)["developer_instructions"]
        )
    return agents


def test_installed_agents_have_no_brace_escapes(installed_agents):
    # No installed agent currently needs doubled braces. Skills have intentional
    # spawn placeholders, so this assertion is limited to the agent roster.
    escaped = {
        name: [
            number
            for number, line in enumerate(text.splitlines(), 1)
            if "{{" in line or "}}" in line
        ]
        for name, text in installed_agents.items()
        if "{{" in text or "}}" in text
    }
    assert not escaped, f"unexpanded brace escapes in installed agents: {escaped}"


def test_installed_agent_json_examples_parse(installed_agents):
    examples = 0
    for name, text in installed_agents.items():
        blocks = re.findall(r"^\s*```json\s*\n(.*?)^\s*```", text, re.MULTILINE | re.DOTALL)
        for number, block in enumerate(blocks, 1):
            # The readability schema uses bare <int> and <int ...> type
            # placeholders. All other placeholders are already JSON strings.
            block = re.sub(r"<int(?:\s[^>\n]*)?>", "0", block)
            try:
                json.loads(block)
            except json.JSONDecodeError as exc:
                pytest.fail(f"{name}, JSON example {number}: {exc}")
            examples += 1
    assert examples > 0, "no fenced JSON examples were checked"
