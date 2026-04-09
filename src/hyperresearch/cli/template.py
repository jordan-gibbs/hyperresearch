"""Template CLI commands."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import success

app = typer.Typer()


@app.command("list")
def template_list(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List available note templates."""
    from hyperresearch.core.templates import list_templates
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
        templates = list_templates(vault.templates_dir)
    except VaultError:
        templates = list_templates()

    if json_output:
        output(success(templates, count=len(templates)), json_mode=True)
    else:
        from rich.table import Table

        table = Table(title="Templates", show_header=True, header_style="bold")
        table.add_column("Name", style="cyan")
        table.add_column("Source", style="dim")
        for t in templates:
            table.add_row(t["name"], t["source"])
        console.print(table)


@app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name"),
) -> None:
    """Preview a template."""
    from hyperresearch.core.templates import get_template
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
        tpl = get_template(name, vault.templates_dir)
    except VaultError:
        tpl = get_template(name)

    if not tpl:
        console.print(f"[red]Template not found:[/] {name}")
        raise typer.Exit(1)

    console.print(tpl)
