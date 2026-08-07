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
        help="Install the selected platform's entry skill + specialist agents at user scope. Skips vault init, project instructions, project hooks, and step skills (those install per project on first use).",
    ),
    steps_only: bool = typer.Option(
        False,
        "--steps-only",
        help="Install only the pipeline step skills for the selected platform. Used internally by the entry skill bootstrap on first use.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Pipeline profile to render skill/agent prompts from (built-in gears: full, premier; plus any [profile.*] defined in .hyperresearch/config.toml). Defaults to the gear persisted by `hyperresearch profile use` (or 'full'). See `hyperresearch profile list`.",
    ),
    platform: str = typer.Option(
        "claude",
        "--platform",
        help="Agent platform integration to install: claude, codex, or both.",
    ),
) -> None:
    """Install hyperresearch and its Claude Code and/or Codex integration."""
    import sys

    from hyperresearch.core.hooks import (
        _install_hyperresearch_step_skills,
        _set_render_state,
        install_global_hooks,
        install_hooks,
    )
    from hyperresearch.core.profiles import ProfileError
    from hyperresearch.core.vault import Vault, VaultError

    platform = platform.lower()
    if platform not in {"claude", "codex", "both"}:
        message = "--platform must be one of: claude, codex, both"
        if json_output:
            output(error(message, "UNKNOWN_PLATFORM"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {message}")
        raise typer.Exit(1)

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
        results: list[str] = []
        if platform in {"claude", "both"}:
            result = _install_hyperresearch_step_skills(target)
            if result:
                results.append(result)
        if platform in {"codex", "both"}:
            from hyperresearch.core.codex import install_codex_step_skills

            result = install_codex_step_skills(target)
            if result:
                results.append(result)
        if json_output:
            # Preserve the pre-Codex JSON shape for the default Claude path.
            steps_installed: str | list[str] | None = (
                results if platform == "both" else results[0] if results else None
            )
            output(
                success(
                    {
                        "steps_installed": steps_installed,
                        "target": str(target),
                        "platform": platform,
                    },
                    vault=None,
                ),
                json_mode=True,
            )
            return
        if results:
            console.print(f"[green]Step skills installed:[/] {target}")
            for result in results:
                console.print(f"  {result}")
        else:
            console.print(f"[dim]Step skills already installed at {target}[/]")
        return

    # Global install path: only the selected platform's entry skill and role
    # prompts. No vault, project instruction file, or step skills. Step skills
    # install per-project, lazily, when the entry skill bootstraps there.
    if global_install:
        from hyperresearch.core.agent_docs import _resolve_executable

        hpr_path = _resolve_executable()
        home = Path.home()
        global_profile = profile if profile is not None else "full"
        _check_profile(global_profile, None)
        global_actions: list[str] = []
        if platform in {"claude", "both"}:
            global_actions.extend(
                install_global_hooks(home, hpr_path=hpr_path, profile=global_profile)
            )
        if platform in {"codex", "both"}:
            from hyperresearch.core.codex import install_codex

            global_actions.extend(
                install_codex(
                    home,
                    hpr_path=hpr_path,
                    profile=global_profile,
                    include_steps=False,
                    include_project_hook=False,
                )
            )

        if json_output:
            output(
                success(
                    {
                        "global": True,
                        "home": str(home),
                        "platform": platform,
                        "hooks_installed": global_actions,
                    },
                    vault=None,
                ),
                json_mode=True,
            )
            return

        console.print(f"[green]Global install ({platform}):[/] {home}")
        if global_actions:
            for action in global_actions:
                console.print(f"  {action}")
        else:
            console.print("[dim]All skills and agents already installed.[/]")
        console.print(f"\n[bold]Ready.[/] hyperresearch is available to {platform}.")
        console.print(
            "[dim]On first /hyperresearch run in a project, the vault, research/ folder, "
            "and the step skills are created in that project's agent skill directory.[/]"
        )
        return

    root = Path(path).resolve()

    # First-time install in an interactive terminal → run the setup TUI instead
    is_new = not (root / ".hyperresearch").exists()
    is_interactive = not json_output and sys.stdin.isatty()
    if is_new and is_interactive and platform == "claude":
        from hyperresearch.cli.setup import setup

        setup(path=path, json_output=False)
        return

    # Step 1: Init vault (skip if already exists)
    try:
        vault = Vault.discover(root)
        vault_action = "existing"
    except VaultError:
        try:
            vault = Vault.init(root, name=name, agent_platform=platform)
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

    # Step 3: Re-inject the selected platform instruction file(s).
    doc_actions = inject_agent_docs(root, platform=platform)

    # Step 4: Install Claude Code hook + skills + subagents (rendered from the
    # gear profile — explicit --profile, else the gear persisted in config)
    project_config = root / ".hyperresearch" / "config.toml"
    project_config_path = project_config if project_config.exists() else None
    project_profile = _default_profile(project_config_path)
    _check_profile(project_profile, project_config_path)
    hook_actions: list[str] = []
    if platform in {"claude", "both"}:
        hook_actions.extend(install_hooks(root, hpr_path=hpr_path, profile=project_profile))
    if platform in {"codex", "both"}:
        from hyperresearch.core.codex import install_codex

        hook_actions.extend(install_codex(root, hpr_path=hpr_path, profile=project_profile))

    # Step 3: Auto-configure crawl4ai if installed
    crawl4ai_status = _setup_crawl4ai(vault)

    # Step 5: Report
    data = {
        "vault_path": str(vault.root),
        "vault": vault_action,
        "platform": platform,
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

        console.print(
            "\n[bold]Ready.[/] Agents will now check the research base before web searches."
        )
        console.print(
            "[dim]Tip: Run 'hyperresearch setup' for interactive configuration (profile, stealth, etc.)[/]"
        )


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

    # Check if the browser is already installed -- against the stack the
    # provider will actually launch: patchright (stealth adapter) pins its
    # own chromium build, so a passing plain-playwright check can mask a
    # missing patchright browser.
    try:
        try:
            from patchright.sync_api import sync_playwright
        except ImportError:
            from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
        return "configured"
    except Exception:
        pass

    # Try to install the browser. The stealth (patchright) adapter pins its
    # OWN chromium build with a separate registry -- `playwright install`
    # does not provide it, and the provider then dies at launch with a
    # missing-executable error. Install patchright's browser when patchright
    # is present; plain playwright is the fallback for non-stealth setups.
    import importlib.util
    import subprocess
    import sys

    installers = []
    if importlib.util.find_spec("patchright") is not None:
        installers.append("patchright")
    installers.append("playwright")
    for mod in installers:
        try:
            subprocess.run(
                [sys.executable, "-m", mod, "install", "chromium"],
                check=True,
                capture_output=True,
            )
            return "browser_installed"
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return "configured"  # best effort — user can install manually
