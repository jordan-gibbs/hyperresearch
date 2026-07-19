"""Cite-check commands — extract citation pairs + mechanical triage."""

from __future__ import annotations

from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.command("extract")
def citecheck_extract(
    vault_tag: str = typer.Argument(..., help="Run tag (pairs file lands in the run workspace)"),
    report: str | None = typer.Option(None, "--report", help="Report path (default: research/notes/final_report_<tag>.md)"),
    sample_rate: float = typer.Option(0.6, "--sample-rate", help="Fraction of weak (non-number-bearing) needs-llm pairs to check; number-bearing sentences are always 100%"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Extract (sentence, citation) pairs from the final report and triage them.

    Auto-passes pairs whose numbers/wording the cited note's claims already
    confirm; writes the sampled needs-llm remainder + dangling citations to
    runs/<tag>/cite-check-pairs.json for the cite-checker agent.
    """
    from hyperresearch.core.citecheck import write_pairs_file
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()
    report_path = Path(report) if report else (
        vault.root / "research" / "notes" / f"final_report_{vault_tag}.md"
    )
    if not report_path.exists():
        msg = f"report not found: {report_path}"
        if json_output:
            output(error(msg, "NO_REPORT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {msg}")
        raise typer.Exit(1)

    result = write_pairs_file(vault, vault_tag, report_path, sample_rate=sample_rate)
    summary = result["summary"]
    data = {
        "pairs_file": str(vault.run_dir(vault_tag) / "cite-check-pairs.json"),
        "summary": summary,
        "sampled_for_llm": len(result["sampled_for_llm"]),
        "dangling": len(result["dangling"]),
    }
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"[green]Cite-check triage:[/] {summary['total']} pairs — "
            f"{summary['supported_mechanical']} auto-passed, "
            f"{data['sampled_for_llm']} sampled for LLM verification, "
            f"{summary['dangling']} dangling"
        )
