"""Index generation CLI commands."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import success

app = typer.Typer()


@app.command("build")
def index_build(
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild all indexes"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Regenerate all index pages."""
    from hyperresearch.core.vault import Vault
    from hyperresearch.indexgen.generator import IndexGenerator

    vault = Vault.discover()
    vault.auto_sync()
    gen = IndexGenerator(vault)
    built = gen.build_all()

    if json_output:
        output(success({"built": built}, count=len(built), vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Built {len(built)} index pages:[/]")
        for p in built:
            console.print(f"  {p}")


@app.command("list")
def index_list(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show which index pages exist."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    index_dir = vault.index_dir
    pages = sorted(p.name for p in index_dir.glob("*.md")) if index_dir.exists() else []

    if json_output:
        output(success(pages, count=len(pages), vault=str(vault.root)), json_mode=True)
    else:
        if not pages:
            console.print("[dim]No index pages. Run 'hyperresearch index build'.[/]")
            return
        for p in pages:
            console.print(f"  [cyan]{p}[/]")


@app.command("show")
def index_show(
    name: str = typer.Argument(..., help="Index page name (e.g. _tags)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Display a specific index page."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    fname = name if name.endswith(".md") else f"{name}.md"
    path = vault.index_dir / fname
    if not path.exists():
        console.print(f"[red]Index page not found:[/] {fname}")
        raise typer.Exit(1)

    content = path.read_text(encoding="utf-8")
    if json_output:
        output(success({"name": name, "content": content}, vault=str(vault.root)), json_mode=True)
    else:
        from rich.markdown import Markdown

        console.print(Markdown(content))
