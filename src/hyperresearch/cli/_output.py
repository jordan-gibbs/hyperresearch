"""Dual-mode output: rich terminal for humans, JSON for LLM agents."""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from hyperresearch.models.output import Envelope

console = Console()
err_console = Console(stderr=True)


def output(data: Any, *, json_mode: bool = False, **kwargs: Any) -> None:
    """Output data in either JSON or rich terminal format."""
    if json_mode:
        _output_json(data)
    else:
        _output_rich(data, **kwargs)


def _output_json(data: Any) -> None:
    """Output as JSON. Uses sys.stdout with UTF-8 to avoid Windows encoding issues."""
    import sys

    if isinstance(data, Envelope) or hasattr(data, "model_dump_json"):
        text = data.model_dump_json(indent=2, exclude_none=True)
    else:
        text = json.dumps(data, indent=2, default=str)

    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def _output_rich(data: Any, **kwargs: Any) -> None:
    """Output in rich terminal format."""
    if isinstance(data, Envelope):
        if not data.ok:
            err_console.print(f"[red bold]Error:[/] {data.error}")
            raise typer.Exit(1)
        _output_rich(data.data, **kwargs)
        return

    if isinstance(data, dict):
        _print_dict(data, **kwargs)
    elif isinstance(data, list):
        _print_list(data, **kwargs)
    elif isinstance(data, str):
        console.print(data)
    else:
        console.print(str(data))


def _print_dict(data: dict, **kwargs: Any) -> None:
    """Pretty-print a dict."""
    for key, value in data.items():
        if isinstance(value, dict):
            console.print(f"[bold]{key}:[/]")
            _print_dict(value)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            console.print(f"\n[bold]{key}:[/]")
            _print_list(value)
        else:
            console.print(f"  [dim]{key}:[/] {value}")


def _print_list(data: list, **kwargs: Any) -> None:
    """Pretty-print a list of items, as a table if they're dicts."""
    if not data:
        console.print("  [dim](none)[/]")
        return

    if isinstance(data[0], dict):
        table = Table(show_header=True, header_style="bold")
        cols = list(data[0].keys())
        for col in cols:
            table.add_column(col)
        for item in data:
            table.add_row(*(str(item.get(c, "")) for c in cols))
        console.print(table)
    else:
        for item in data:
            console.print(f"  - {item}")


def print_note_summary(notes: list[dict], title: str = "Notes") -> None:
    """Print a table of notes."""
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    table.add_column("Status", style="yellow")
    table.add_column("Tags", style="green")
    table.add_column("Words", justify="right", style="dim")
    for n in notes:
        tags = ", ".join(n.get("tags", []))
        table.add_row(
            n.get("id", ""),
            n.get("title", ""),
            n.get("status", ""),
            tags,
            str(n.get("word_count", "")),
        )
    console.print(table)


def print_vault_status(data: dict) -> None:
    """Print vault status in a nice tree format."""
    tree = Tree(f"[bold]{data.get('vault_name', 'Vault')}[/]")
    notes = tree.add("[bold]Notes[/]")
    nd = data.get("notes", {})
    notes.add(f"Total: {nd.get('total', 0)}")
    for status, count in nd.get("by_status", {}).items():
        notes.add(f"{status}: {count}")

    tags = tree.add("[bold]Tags[/]")
    tags.add(f"Unique: {data.get('tags', {}).get('total_unique', 0)}")

    graph = tree.add("[bold]Graph[/]")
    gd = data.get("graph", {})
    graph.add(f"Links: {gd.get('total_links', 0)}")
    graph.add(f"Broken: {gd.get('broken_links', 0)}")
    graph.add(f"Orphans: {gd.get('orphan_notes', 0)}")

    tree.add(f"[dim]Words: {data.get('total_words', 0):,}[/]")
    console.print(tree)
