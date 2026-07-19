"""Tests for the prompt-template render layer (core/render.py)."""

from __future__ import annotations

import pytest
from jinja2 import UndefinedError

from hyperresearch.core.render import (
    build_render_context,
    insert_after_frontmatter,
    render_header,
    render_prompt,
)


@pytest.fixture(scope="module")
def ctx():
    return build_render_context(None, primary="full")


class TestDelimiters:
    def test_variables_use_double_angle(self, ctx):
        assert render_prompt("min << p.source_min >> sources", ctx) == "min 45 sources"

    def test_standard_jinja_braces_pass_through(self, ctx):
        # Skill prose legitimately contains {{...}} placeholders and JSON braces;
        # they must survive rendering untouched.
        text = "> {{paste research/query-<vault_tag>.md body}}\n{\"total_findings\": 3}"
        assert render_prompt(text, ctx) == text

    def test_blocks_use_angle_percent(self, ctx):
        out = render_prompt("<% if p.utility_scoring %>score<% endif %>", ctx)
        assert out == "score"

    def test_unknown_variable_raises(self, ctx):
        with pytest.raises(UndefinedError):
            render_prompt("<< p.does_not_exist >>", ctx)


class TestFilters:
    def test_dash_is_en_dash(self, ctx):
        assert render_prompt("<< p.source_target|dash >>", ctx) == "55–80"

    def test_hyphen(self, ctx):
        assert render_prompt("<< p.fetcher_chase|hyphen >>", ctx) == "3-8"


class TestContext:
    def test_all_profiles_exposed_by_name(self, ctx):
        out = render_prompt("<< light.source_min >>/<< full.source_min >>", ctx)
        assert out == "10/45"

    def test_primary_alias(self):
        ctx_light = build_render_context(None, primary="light")
        assert render_prompt("<< p.source_min >>", ctx_light) == "10"

    def test_user_overlay_flows_through(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[profile.full]\nsource_min = 200\n", encoding="utf-8")
        ctx2 = build_render_context(cfg, primary="full")
        assert render_prompt("<< p.source_min >>", ctx2) == "200"


class TestHeaderInsertion:
    def test_inserted_after_frontmatter(self):
        content = "---\nname: x\n---\n\n# Body\n"
        out = insert_after_frontmatter(content, "<!-- hdr -->")
        assert out.startswith("---\nname: x\n---\n<!-- hdr -->\n\n# Body\n")

    def test_no_frontmatter_prepends(self):
        out = insert_after_frontmatter("# Body\n", "<!-- hdr -->")
        assert out == "<!-- hdr -->\n# Body\n"

    def test_header_names_profile_and_version(self):
        h = render_header("dissertation", "9.9.9")
        assert "dissertation" in h and "9.9.9" in h
        assert h.startswith("<!--") and h.endswith("-->")
