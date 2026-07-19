"""Install command — one-step setup: vault init + agent hooks + docs injection."""

from __future__ import annotations

from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def install(
    path: str = typer.Argument(".", help="Path to install in"),
    name: str = typer.Option("Research Base", "--name", "-n", help="Vault name"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
    global_install: bool = typer.Option(
        False,
        "--global",
        "-g",
        help="Install Claude Code entry skill + agents to ~/.claude/ so /hyperresearch works in every Claude Code session anywhere. Skips vault init, CLAUDE.md, and the 16 step skills (those happen per-project on first /hyperresearch run).",
    ),
    steps_only: bool = typer.Option(
        False,
        "--steps-only",
        help="Install only the 16 step skills to <PATH>/.claude/skills/. Used internally by the entry skill bootstrap on first /hyperresearch invocation in a project. Not normally invoked by users.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Pipeline profile to render skill/agent prompts from (built-in gears: full, premier; plus any [profile.*] defined in .hyperresearch/config.toml). Defaults to the gear persisted by `hyperresearch profile use` (or 'full'). See `hyperresearch profile list`.",
    ),
) -> None:
    """Install hyperresearch: init vault + inject CLAUDE.md + install Claude Code hooks."""
    import sys

    from hyperresearch.core.hooks import (
        _install_hyperresearch_step_skills,
        _set_render_state,
        install_global_hooks,
        install_hooks,
    )
    from hyperresearch.core.profiles import ProfileError
    from hyperresearch.core.vault import Vault, VaultError

    # No explicit --profile → use the gear persisted by `hpr profile use`
    # in the target's config (falling back to "full").
    def _default_profile(config_path: Path | None) -> str:
        if profile is not None:
            return profile
        if config_path is not None and config_path.exists():
            from hyperresearch.core.config import VaultConfig

            return VaultConfig.load(config_path).pipeline_profile
        return "full"

    # Validate the profile early so a typo fails before any files are written.
    def _check_profile(resolved: str, config_path: Path | None) -> None:
        from hyperresearch.core.profiles import resolve_profile

        try:
            resolve_profile(resolved, config_path)
        except ProfileError as e:
            if json_output:
                output(error(str(e), "UNKNOWN_PROFILE"), json_mode=True)
            else:
                console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)

    # Steps-only path: lazy install of the 16 step skills to a project's
    # .claude/skills/. Called by the entry skill's bootstrap on first
    # /hyperresearch in a project (after a global install). Cheap no-op
    # on subsequent invocations.
    if steps_only:
        target = Path(path).resolve()
        steps_config = target / ".hyperresearch" / "config.toml"
        steps_config_path = steps_config if steps_config.exists() else None
        steps_profile = _default_profile(steps_config_path)
        _check_profile(steps_profile, steps_config_path)
        _set_render_state(steps_profile, steps_config_path)
        result = _install_hyperresearch_step_skills(target)
        if json_output:
            output(
                success({"steps_installed": result, "target": str(target)}, vault=None),
                json_mode=True,
            )
            return
        if result:
            console.print(f"[green]Step skills installed:[/] {target}/.claude/skills/")
            console.print(f"  {result}")
        else:
            console.print(f"[dim]Step skills already installed at {target}/.claude/skills/[/]")
        return

    # Global install path: only the user-level Claude Code entry skill +
    # agents. No vault, no CLAUDE.md, no step skills — pure "make the
    # slash command available everywhere" mode. Step skills install
    # per-project, lazily, when the entry skill bootstrap calls
    # `hyperresearch install --steps-only .` on first invocation.
    if global_install:
        from hyperresearch.core.agent_docs import _resolve_executable

        hpr_path = _resolve_executable()
        home = Path.home()
        global_profile = profile if profile is not None else "full"
        _check_profile(global_profile, None)
        hook_actions = install_global_hooks(home, hpr_path=hpr_path, profile=global_profile)

        if json_output:
            output(
                success(
                    {"global": True, "home": str(home), "hooks_installed": hook_actions},
                    vault=None,
                ),
                json_mode=True,
            )
            return

        console.print(f"[green]Global install:[/] {home}/.claude/")
        if hook_actions:
            for action in hook_actions:
                console.print(f"  {action}")
        else:
            console.print("[dim]All skills and agents already installed.[/]")
        console.print(
            "\n[bold]Ready.[/] /hyperresearch is now available in every Claude Code session."
        )
        console.print(
            "[dim]On first /hyperresearch run in a project, the vault, research/ folder, "
            "and the 16 step skills are created in that project's .claude/.[/]"
        )
        return

    root = Path(path).resolve()

    # First-time install in an interactive terminal → run the setup TUI instead
    is_new = not (root / ".hyperresearch").exists()
    is_interactive = not json_output and sys.stdin.isatty()
    if is_new and is_interactive:
        from hyperresearch.cli.setup import setup

        setup(path=path, json_output=False)
        return

    # Step 1: Init vault (skip if already exists)
    try:
        vault = Vault.discover(root)
        vault_action = "existing"
    except VaultError:
        try:
            vault = Vault.init(root, name=name)
            vault_action = "created"
        except VaultError as e:
            if json_output:
                output(error(str(e), "INIT_ERROR"), json_mode=True)
            else:
                console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)

    # Step 2: Resolve the hyperresearch executable path
    from hyperresearch.core.agent_docs import _resolve_executable, inject_agent_docs

    hpr_path = _resolve_executable()

    # Step 3: Always re-inject CLAUDE.md (updates blurb + path)
    doc_actions = inject_agent_docs(root)

    # Step 4: Install Claude Code hook + skills + subagents (rendered from the
    # gear profile — explicit --profile, else the gear persisted in config)
    project_config = root / ".hyperresearch" / "config.toml"
    project_config_path = project_config if project_config.exists() else None
    project_profile = _default_profile(project_config_path)
    _check_profile(project_profile, project_config_path)
    hook_actions = install_hooks(root, hpr_path=hpr_path, profile=project_profile)

    # Step 3: Auto-configure crawl4ai if installed
    crawl4ai_status = _setup_crawl4ai(vault)

    # Step 5: Report
    data = {
        "vault_path": str(vault.root),
        "vault": vault_action,
        "agent_docs": doc_actions,
        "hooks_installed": hook_actions,
        "crawl4ai": crawl4ai_status,
    }

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        if vault_action == "created":
            console.print(f"[green]Vault created:[/] {vault.root}")
        else:
            console.print(f"[dim]Vault exists:[/] {vault.root}")

        if doc_actions:
            console.print("[green]Agent docs:[/]")
            for action in doc_actions:
                console.print(f"  {action}")

        if hook_actions:
            console.print("[green]Hooks installed:[/]")
            for action in hook_actions:
                console.print(f"  {action}")
        else:
            console.print("[dim]All hooks already installed.[/]")

        if crawl4ai_status == "configured":
            console.print("[green]crawl4ai:[/] detected, set as default provider + browser ready")
        elif crawl4ai_status == "browser_installed":
            console.print("[green]crawl4ai:[/] browser installed + set as default provider")
        elif crawl4ai_status == "not_installed":
            console.print(
                "[dim]crawl4ai:[/] not installed. "
                "For local headless browsing: pip install hyperresearch[crawl4ai]"
            )

        console.print("\n[bold]Ready.[/] Agents will now check the research base before web searches.")
        console.print("[dim]Tip: Run 'hyperresearch setup' for interactive configuration (profile, stealth, etc.)[/]")


def _setup_crawl4ai(vault) -> str:
    """Detect crawl4ai, install browser if needed, set as default provider.

    Returns: 'configured' (already ready), 'browser_installed' (just set up),
             'not_installed' (crawl4ai not available).
    """
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        return "not_installed"

    # Set crawl4ai as the default provider if still on builtin
    if vault.config.web_provider == "builtin":
        vault.config.web_provider = "crawl4ai"
        vault.config.save(vault.config_path)

    # Check if browser is already installed
    try:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
        return "configured"
    except Exception:
        pass

    # Try to install the browser
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
        return "configured"  # best effort — user can install manually
