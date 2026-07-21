"""Install command — one-step setup: vault init + agent integrations + docs injection."""

from __future__ import annotations

from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.core.agent_platforms import selected_agents as _selected_agents
from hyperresearch.models.output import error, success


def install(
    path: str = typer.Argument(".", help="Path to install in"),
    name: str = typer.Option("Research Base", "--name", "-n", help="Vault name"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
    global_install: bool = typer.Option(
        False,
        "--global",
        "-g",
        help=(
            "Install the selected agent platform's entry skill and custom agents globally. "
            "Skips vault init and project docs; step skills install per project on first use."
        ),
    ),
    steps_only: bool = typer.Option(
        False,
        "--steps-only",
        help=(
            "Install only the 16 project step skills for the selected agent platform. "
            "Used internally by the global entry skill bootstrap."
        ),
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help=(
            "Pipeline profile to render skill/agent prompts from (built-in gears: full, "
            "premier; plus any [profile.*] in .hyperresearch/config.toml)."
        ),
    ),
    agent: str = typer.Option(
        "claude",
        "--agent",
        help="Agent platform to install: claude, codex, or both.",
    ),
) -> None:
    """Install hyperresearch for Claude Code, Codex, or both."""
    import sys

    from hyperresearch.core.hooks import (
        _install_hyperresearch_step_skills,
        _set_render_state,
        install_global_hooks,
        install_hooks,
    )
    from hyperresearch.core.profiles import ProfileError
    from hyperresearch.core.vault import Vault, VaultError

    try:
        platforms = _selected_agents(agent)
    except ValueError as exc:
        if json_output:
            output(error(str(exc), "UNKNOWN_AGENT_PLATFORM"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(1)

    def _default_profile(config_path: Path | None) -> str:
        if profile is not None:
            return profile
        if config_path is not None and config_path.exists():
            from hyperresearch.core.config import VaultConfig

            return VaultConfig.load(config_path).pipeline_profile
        return "full"

    def _check_profile(resolved: str, config_path: Path | None) -> None:
        from hyperresearch.core.profiles import resolve_profile

        try:
            resolve_profile(resolved, config_path)
        except ProfileError as exc:
            if json_output:
                output(error(str(exc), "UNKNOWN_PROFILE"), json_mode=True)
            else:
                console.print(f"[red]Error:[/] {exc}")
            raise typer.Exit(1)

    if steps_only:
        target = Path(path).resolve()
        steps_config = target / ".hyperresearch" / "config.toml"
        steps_config_path = steps_config if steps_config.exists() else None
        steps_profile = _default_profile(steps_config_path)
        _check_profile(steps_profile, steps_config_path)
        steps_actions: list[str] = []

        if "claude" in platforms:
            _set_render_state(steps_profile, steps_config_path)
            result = _install_hyperresearch_step_skills(target)
            if result:
                steps_actions.append(result)

        if "codex" in platforms:
            from hyperresearch.core.codex import install_codex

            steps_actions.extend(install_codex(target, profile=steps_profile, steps_only=True))

        data = {
            "steps_installed": steps_actions,
            "target": str(target),
            "agent_platforms": list(platforms),
        }
        if json_output:
            output(success(data, vault=None), json_mode=True)
            return

        if steps_actions:
            console.print(f"[green]Step skills installed:[/] {target}")
            for action in steps_actions:
                console.print(f"  {action}")
        else:
            console.print(f"[dim]Step skills already installed at {target}[/]")
        return

    if global_install:
        from hyperresearch.core.agent_docs import _resolve_executable

        hpr_path = _resolve_executable()
        home = Path.home()
        global_profile = profile if profile is not None else "full"
        _check_profile(global_profile, None)
        global_actions: list[str] = []

        if "claude" in platforms:
            global_actions.extend(
                install_global_hooks(home, hpr_path=hpr_path, profile=global_profile)
            )
        if "codex" in platforms:
            from hyperresearch.core.codex import install_codex

            global_actions.extend(
                install_codex(
                    home,
                    hpr_path=hpr_path,
                    profile=global_profile,
                    global_install=True,
                )
            )

        data = {
            "global": True,
            "home": str(home),
            "agent_platforms": list(platforms),
            "hooks_installed": global_actions,
        }
        if json_output:
            output(success(data, vault=None), json_mode=True)
            return

        console.print(f"[green]Global install:[/] {home}")
        if global_actions:
            for action in global_actions:
                console.print(f"  {action}")
        else:
            console.print("[dim]All selected skills and agents already installed.[/]")

        from hyperresearch.core.agent_platforms import invocation_hint

        console.print(f"\n[bold]Ready.[/] Start with {invocation_hint(platforms)} <query>.")
        console.print(
            "[dim]On first use in a project, the entry skill initializes the vault and "
            "installs project step skills.[/]"
        )
        return

    root = Path(path).resolve()

    is_new = not (root / ".hyperresearch").exists()
    is_interactive = not json_output and sys.stdin.isatty()
    if is_new and is_interactive:
        from hyperresearch.cli.setup import setup

        setup(path=path, json_output=False, agent=agent)
        return

    try:
        vault = Vault.discover(root)
        vault_action = "existing"
    except VaultError:
        try:
            vault = Vault.init(root, name=name, inject_docs="claude" in platforms)
            vault_action = "created"
        except VaultError as exc:
            if json_output:
                output(error(str(exc), "INIT_ERROR"), json_mode=True)
            else:
                console.print(f"[red]Error:[/] {exc}")
            raise typer.Exit(1)

    from hyperresearch.core.agent_docs import _resolve_executable

    hpr_path = _resolve_executable()
    doc_actions: list[str] = []
    integration_actions: list[str] = []

    if "claude" in platforms:
        from hyperresearch.core.agent_docs import inject_agent_docs

        doc_actions.extend(inject_agent_docs(root))
    if "codex" in platforms:
        from hyperresearch.core.codex import inject_codex_docs

        doc_actions.extend(inject_codex_docs(root, hpr_path=hpr_path))

    project_config = root / ".hyperresearch" / "config.toml"
    project_config_path = project_config if project_config.exists() else None
    project_profile = _default_profile(project_config_path)
    _check_profile(project_profile, project_config_path)

    if "claude" in platforms:
        integration_actions.extend(install_hooks(root, hpr_path=hpr_path, profile=project_profile))
    if "codex" in platforms:
        from hyperresearch.core.codex import install_codex

        integration_actions.extend(
            install_codex(root, hpr_path=hpr_path, profile=project_profile)
        )

    crawl4ai_status = _setup_crawl4ai(vault)
    data = {
        "vault_path": str(vault.root),
        "vault": vault_action,
        "agent_platforms": list(platforms),
        "agent_docs": doc_actions,
        "hooks_installed": integration_actions,
        "crawl4ai": crawl4ai_status,
    }

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
        return

    if vault_action == "created":
        console.print(f"[green]Vault created:[/] {vault.root}")
    else:
        console.print(f"[dim]Vault exists:[/] {vault.root}")

    if doc_actions:
        console.print("[green]Agent docs:[/]")
        for action in doc_actions:
            console.print(f"  {action}")

    if integration_actions:
        console.print("[green]Agent integrations installed:[/]")
        for action in integration_actions:
            console.print(f"  {action}")
    else:
        console.print("[dim]All selected integrations already installed.[/]")

    if crawl4ai_status == "configured":
        console.print("[green]crawl4ai:[/] detected, set as default provider + browser ready")
    elif crawl4ai_status == "browser_installed":
        console.print("[green]crawl4ai:[/] browser installed + set as default provider")
    elif crawl4ai_status == "not_installed":
        console.print(
            "[dim]crawl4ai:[/] not installed. "
            "For local headless browsing: pip install hyperresearch[crawl4ai]"
        )

    from hyperresearch.core.agent_platforms import invocation_hint

    console.print(f"\n[bold]Ready.[/] Start with {invocation_hint(platforms)} <query>.")
    console.print(
        "[dim]Tip: Run 'hyperresearch setup --agent "
        f"{agent}' for interactive browser/profile configuration.[/]"
    )


def _setup_crawl4ai(vault) -> str:
    """Detect crawl4ai, install browser if needed, and set it as default provider."""
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        return "not_installed"

    if vault.config.web_provider == "builtin":
        vault.config.web_provider = "crawl4ai"
        vault.config.save(vault.config_path)

    try:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
        return "configured"
    except Exception:
        pass

    import subprocess
    import sys

    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
        )
        return "browser_installed"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "configured"
