"""Markdown to HTML renderer with [[wiki-link]] resolution."""

from __future__ import annotations

import html
import re

# Simple markdown patterns
MD_PATTERNS = [
    # Headers
    (re.compile(r"^######\s+(.+)$", re.MULTILINE), r"<h6>\1</h6>"),
    (re.compile(r"^#####\s+(.+)$", re.MULTILINE), r"<h5>\1</h5>"),
    (re.compile(r"^####\s+(.+)$", re.MULTILINE), r"<h4>\1</h4>"),
    (re.compile(r"^###\s+(.+)$", re.MULTILINE), r"<h3>\1</h3>"),
    (re.compile(r"^##\s+(.+)$", re.MULTILINE), r"<h2>\1</h2>"),
    (re.compile(r"^#\s+(.+)$", re.MULTILINE), r"<h1>\1</h1>"),
    # Bold/italic
    (re.compile(r"\*\*\*(.+?)\*\*\*"), r"<strong><em>\1</em></strong>"),
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\*(.+?)\*"), r"<em>\1</em>"),
    # Code
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    # Links
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2">\1</a>'),
    # Images
    (re.compile(r"!\[([^\]]*)\]\(([^)]+)\)"), r'<img src="\2" alt="\1">'),
    # Horizontal rule
    (re.compile(r"^---+$", re.MULTILINE), r"<hr>"),
    # Blockquotes
    (re.compile(r"^>\s*(.+)$", re.MULTILINE), r"<blockquote>\1</blockquote>"),
]


def render_markdown(body: str) -> str:
    """Convert markdown body to HTML, resolving [[wiki-links]]."""
    # Escape HTML first
    text = html.escape(body)

    # Handle code blocks (preserve them)
    code_blocks = []
    def save_code_block(m):
        code_blocks.append(m.group(0))
        return f"\x00CODE{len(code_blocks) - 1}\x00"

    text = re.sub(r"```(\w*)\n(.*?)```", save_code_block, text, flags=re.DOTALL)

    # Apply markdown patterns
    for pattern, replacement in MD_PATTERNS:
        text = pattern.sub(replacement, text)

    # Wiki links: [[target|display]] or [[target]]
    def replace_wiki_link(m):
        full = m.group(0)
        # Unescape the brackets that html.escape would have converted
        inner = full[2:-2]  # strip [[ and ]]
        if "|" in inner:
            target, display = inner.split("|", 1)
        else:
            target = display = inner
        target = target.strip()
        display = display.strip()
        return f'<a href="/note/{target}" class="wiki-link">{display}</a>'

    text = re.sub(r"\[\[([^\]]+)\]\]", replace_wiki_link, text)

    # Lists (simple)
    text = re.sub(r"^- (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
    text = re.sub(r"(<li>.*</li>\n?)+", lambda m: f"<ul>{m.group(0)}</ul>", text)

    # Tables
    lines = text.split("\n")
    in_table = False
    table_lines = []
    result_lines = []
    for line in lines:
        if "|" in line and line.strip().startswith("|"):
            if not in_table:
                in_table = True
                table_lines = []
            table_lines.append(line)
        else:
            if in_table:
                result_lines.append(_render_table(table_lines))
                in_table = False
                table_lines = []
            result_lines.append(line)
    if in_table:
        result_lines.append(_render_table(table_lines))
    text = "\n".join(result_lines)

    # Restore code blocks
    for i, block in enumerate(code_blocks):
        html.escape(block)
        lang_match = re.match(r"```(\w+)\n", block)
        lang = lang_match.group(1) if lang_match else ""
        code_content = re.sub(r"```\w*\n|```", "", block)
        code_html = f'<pre><code class="language-{lang}">{html.escape(code_content)}</code></pre>'
        text = text.replace(f"\x00CODE{i}\x00", code_html)

    # Paragraphs: wrap standalone lines
    text = re.sub(r"\n\n+", "\n</p>\n<p>\n", text)
    if not text.startswith("<"):
        text = "<p>\n" + text
    if not text.rstrip().endswith(">"):
        text = text + "\n</p>"

    return text


def _render_table(lines: list[str]) -> str:
    """Render a markdown table to HTML."""
    if len(lines) < 2:
        return "\n".join(lines)

    rows = []
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip("|").split("|")]
        if i == 1 and all(re.match(r"^[-:]+$", c.strip()) for c in cells):
            continue  # Skip separator row
        tag = "th" if i == 0 else "td"
        row = "".join(f"<{tag}>{c}</{tag}>" for c in cells)
        rows.append(f"<tr>{row}</tr>")

    return f'<table class="md-table">{"".join(rows)}</table>'
