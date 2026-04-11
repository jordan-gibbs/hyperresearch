"""Hyperresearch CLI — main typer application."""

import os
import sys

# Fix Windows console encoding — crawl4ai's rich logger uses Unicode chars that
# crash on Windows cp1252 consoles. Reconfigure streams to UTF-8 at startup.
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

import typer

from hyperresearch import __version__


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"hyperresearch v{__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="hyperresearch",
    help="Agent-driven research knowledge base.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version"),
) -> None:
    pass


# Root-level commands
from hyperresearch.cli.dedup import dedup as _dedup
from hyperresearch.cli.fetch import fetch as _fetch
from hyperresearch.cli.import_cmd import import_vault as _import
from hyperresearch.cli.install import install as _install
from hyperresearch.cli.main import init as _init
from hyperresearch.cli.main import status as _status
from hyperresearch.cli.main import sync as _sync
from hyperresearch.cli.mcp_cmd import mcp as _mcp
from hyperresearch.cli.note import note_show as _show
from hyperresearch.cli.repair import repair as _repair
from hyperresearch.cli.research import research as _research
from hyperresearch.cli.search import search as _search
from hyperresearch.cli.serve import serve as _serve
from hyperresearch.cli.tag import tag_list as _tags
from hyperresearch.cli.watch import watch as _watch

app.command("install")(_install)

from hyperresearch.cli.setup import setup as _setup

app.command("setup")(_setup)
app.command("init")(_init)
app.command("status")(_status)
app.command("sync")(_sync)
app.command("search")(_search)
app.command("fetch")(_fetch)

from hyperresearch.cli.fetch_batch import fetch_batch as _fetch_batch

app.command("fetch-batch")(_fetch_batch)
app.command("research")(_research)
app.command("tags")(_tags)
app.command("show", hidden=True)(_show)
app.command("dedup")(_dedup)
app.command("import")(_import)
app.command("repair")(_repair)
app.command("watch")(_watch)
app.command("serve")(_serve)
app.command("mcp")(_mcp)

# Sub-apps
from hyperresearch.cli.batch import app as batch_app
from hyperresearch.cli.config_cmd import app as config_app
from hyperresearch.cli.export import app as export_app
from hyperresearch.cli.git_cmd import app as git_app
from hyperresearch.cli.graph import app as graph_app
from hyperresearch.cli.index import app as index_app
from hyperresearch.cli.lint import app as lint_app
from hyperresearch.cli.note import app as note_app
from hyperresearch.cli.tag import app as tag_app
from hyperresearch.cli.template import app as template_app
from hyperresearch.cli.topic import app as topic_app

app.add_typer(note_app, name="note", help="Note CRUD operations.")
app.add_typer(graph_app, name="graph", help="Knowledge graph and link analysis.")
app.add_typer(index_app, name="index", help="Auto-generated index pages.")
app.add_typer(lint_app, name="lint", help="Health-check the vault.")
app.add_typer(export_app, name="export", help="Export notes.")
app.add_typer(config_app, name="config", help="Configuration.")
app.add_typer(topic_app, name="topic", help="Topic hierarchy.")
app.add_typer(batch_app, name="batch", help="Bulk operations.")
app.add_typer(template_app, name="template", help="Note templates.")
app.add_typer(git_app, name="git", help="Git integration.")
app.add_typer(tag_app, name="tag", help="Tag management.")

from hyperresearch.cli.assets import app as assets_app
from hyperresearch.cli.link import app as link_app
from hyperresearch.cli.sources import app as sources_app

app.add_typer(sources_app, name="sources", help="Fetched web sources.")
app.add_typer(assets_app, name="assets", help="Downloaded images, screenshots, and media.")
app.add_typer(link_app, name="link", help="Auto-discover and insert wiki-links.")
