"""Topic tree CLI commands — hierarchical parent navigation."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import success

app = typer.Typer()


@app.command("tree")
def topic_tree(
    depth: int = typer.Option(0, "--depth", "-d", help="Max depth (0=unlimited)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show the full topic hierarchy as a tree."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute(
        "SELECT parent, COUNT(*) as count FROM notes "
        "WHERE parent IS NOT NULL AND type NOT IN ('index') "
        "GROUP BY parent ORDER BY parent"
    ).fetchall()

    # Collect all unique topic paths and their counts
    topics = {}
    for row in rows:
        path = row["parent"]
        topics[path] = row["count"]
        # Add ancestor paths with 0 count if missing
        parts = path.split("/")
        for i in range(1, len(parts)):
            ancestor = "/".join(parts[:i])
            if ancestor not in topics:
                topics[ancestor] = 0

    if json_output:
        data = [{"topic": k, "direct_notes": v} for k, v in sorted(topics.items())]
        output(success(data, count=len(data), vault=str(vault.root)), json_mode=True)
    else:
        if not topics:
            console.print("[dim]No topics found. Set 'parent' in note frontmatter.[/]")
            return

        from rich.tree import Tree

        root = Tree("[bold]Topics[/]")
        _build_rich_tree(root, topics, depth)
        console.print(root)


def _build_rich_tree(parent_node, topics: dict, max_depth: int, prefix: str = "", current_depth: int = 0):
    """Recursively build a Rich tree from topic paths."""
    if max_depth > 0 and current_depth >= max_depth:
        return

    # Find direct children at this level
    children: dict[str, int] = {}
    for path, count in sorted(topics.items()):
        if prefix:
            if not path.startswith(prefix + "/"):
                continue
            remainder = path[len(prefix) + 1:]
        else:
            remainder = path

        if "/" not in remainder:
            children[remainder] = count

    for child_name, count in sorted(children.items()):
        full_path = f"{prefix}/{child_name}" if prefix else child_name
        # Count all notes under this subtree
        subtree_count = sum(v for k, v in topics.items() if k == full_path or k.startswith(full_path + "/"))
        label = f"[cyan]{child_name}[/]"
        if count > 0:
            label += f" ({count} notes)"
        if subtree_count > count:
            label += f" [dim]({subtree_count} total)[/]"
        child_node = parent_node.add(label)
        _build_rich_tree(child_node, topics, max_depth, full_path, current_depth + 1)


@app.command("list")
def topic_list(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Flat list of all topics with note counts."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute(
        "SELECT parent, COUNT(*) as count FROM notes "
        "WHERE parent IS NOT NULL AND type NOT IN ('index') "
        "GROUP BY parent ORDER BY count DESC"
    ).fetchall()

    topics = [{"topic": r["parent"], "count": r["count"]} for r in rows]

    if json_output:
        output(success(topics, count=len(topics), vault=str(vault.root)), json_mode=True)
    else:
        from rich.table import Table

        table = Table(title="Topics", show_header=True, header_style="bold")
        table.add_column("Topic", style="cyan")
        table.add_column("Notes", justify="right")
        for t in topics:
            table.add_row(t["topic"], str(t["count"]))
        console.print(table)


@app.command("show")
def topic_show(
    topic: str = typer.Argument(..., help="Topic path (e.g. ml/deep-learning)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show all notes under a topic (including subtopics)."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    # Match exact and subtopics
    rows = vault.db.execute(
        """SELECT n.id, n.title, n.parent, n.status, n.word_count, n.summary,
           (SELECT GROUP_CONCAT(t.tag, ',') FROM tags t WHERE t.note_id = n.id) as tag_list
        FROM notes n
        WHERE (n.parent = ? OR n.parent LIKE ?)
          AND n.type NOT IN ('index')
        ORDER BY n.parent, n.title""",
        (topic, topic + "/%"),
    ).fetchall()

    notes = []
    for row in rows:
        tag_list = row["tag_list"].split(",") if row["tag_list"] else []
        notes.append({
            "id": row["id"],
            "title": row["title"],
            "parent": row["parent"],
            "status": row["status"],
            "tags": tag_list,
            "word_count": row["word_count"],
            "summary": row["summary"],
        })

    if json_output:
        output(success({"topic": topic, "notes": notes}, count=len(notes), vault=str(vault.root)), json_mode=True)
    else:
        if not notes:
            console.print(f"[dim]No notes under topic '{topic}'[/]")
            return
        console.print(f"[bold]Topic: {topic}[/] ({len(notes)} notes)\n")
        for n in notes:
            summary = f" — {n['summary']}" if n["summary"] else ""
            console.print(f"  [cyan]{n['id']}[/] {n['title']}{summary} [dim]`{n['status']}`[/]")
