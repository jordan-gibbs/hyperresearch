"""Run levers — render/update the per-run posture shim files."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


def _discover(json_output: bool):
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e


def _fail(msg: str, code: str, json_output: bool) -> None:
    if json_output:
        output(error(msg, code), json_mode=True)
    else:
        console.print(f"[red]Error:[/] {msg}")
    raise typer.Exit(1)


@app.command("render")
def levers_render(
    vault_tag: str = typer.Argument(..., help="Run tag (shims land in runs/<tag>/shims/)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Render the four role shim files from the run's decomposition levers.

    Reads the "levers" block of runs/<tag>/prompt-decomposition.json
    (defaults: register=analyze, inference_depth=standard when absent) and
    writes shims/{research,drafting,critics,polish}.md for the orchestrator
    to paste verbatim into subagent spawn prompts.
    """
    from hyperresearch.core.levers import LeverError, render_shims

    vault = _discover(json_output)
    vault.auto_sync()
    try:
        result = render_shims(vault, vault_tag)
    except LeverError as e:
        _fail(str(e), "LEVER_ERROR", json_output)
        return
    levers = result["levers"]
    if json_output:
        output(success(result, vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"[green]Levers rendered:[/] register={levers['register']} "
            f"inference_depth={levers['inference_depth']} "
            f"({len(result['files'])} shim files)"
        )


@app.command("set")
def levers_set(
    vault_tag: str = typer.Argument(..., help="Run tag"),
    assignments: list[str] = typer.Argument(..., help="key=value pairs (register, inference_depth, domain_notes)"),
    rerender: bool = typer.Option(False, "--rerender", help="Re-render the shim files after updating"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Update the run's levers block (e.g. step 4 upgrading inference_depth).

    Example: hpr levers set my-run inference_depth=deep --rerender
    """
    from hyperresearch.core.levers import LeverError, render_shims, set_levers

    vault = _discover(json_output)
    vault.auto_sync()

    updates: dict = {}
    for pair in assignments:
        if "=" not in pair:
            _fail(f"expected key=value, got '{pair}'", "LEVER_ERROR", json_output)
        key, value = pair.split("=", 1)
        updates[key.strip()] = value.strip()

    try:
        levers = set_levers(vault, vault_tag, updates)
        result = {"levers": levers, "rerendered": rerender}
        if rerender:
            result = {**render_shims(vault, vault_tag), "rerendered": True}
    except LeverError as e:
        _fail(str(e), "LEVER_ERROR", json_output)
        return
    if json_output:
        output(success(result, vault=str(vault.root)), json_mode=True)
    else:
        lv = result["levers"]
        suffix = " (shims re-rendered)" if rerender else ""
        console.print(
            f"[green]Levers updated:[/] register={lv['register']} "
            f"inference_depth={lv['inference_depth']}{suffix}"
        )
