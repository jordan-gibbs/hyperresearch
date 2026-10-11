"""Interactive setup TUI — first-time onboarding and settings configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

console = Console()


def setup(
    path: str = typer.Argument(".", help="Path to set up"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output (non-interactive)"),
) -> None:
    """Interactive setup — configure hyperresearch step by step."""
    if json_output or not sys.stdin.isatty():
        import subprocess

        cmd = [sys.executable, "-m", "hyperresearch", "install", path]
        if json_output:
            cmd.append("--json")
        raise typer.Exit(subprocess.call(cmd))

    root = Path(path).resolve()

    console.print()
    console.print(
        Panel(
            "[bold cyan]hyperresearch[/]\n"
            "[dim]Agent-driven research knowledge base[/]\n\n"
            "[dim]Your AI agents will collect, search, and synthesize\n"
            "web research into a persistent, searchable wiki.[/]",
            border_style="cyan",
            padding=(1, 4),
        )
    )

    vault_name = "Research Base"

    # ── Step 1: Web Provider ──────────────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 1[/]  Web Provider", style="cyan"))
    console.print()

    has_crawl4ai = _check_crawl4ai()
    provider = _choose_provider(has_crawl4ai, _current_provider(root))
    # The local browser runs as the provider itself or as Firecrawl's fallback.
    uses_browser = has_crawl4ai and provider in ("crawl4ai", "firecrawl")

    # ── Step 2: Browser Profile ───────────────────────────────────
    profile = ""
    if uses_browser:
        console.print()
        console.print(Rule("[bold]Step 2[/]  Browser Profile", style="cyan"))
        console.print()
        console.print("  A login profile lets hyperresearch access sites you're")
        console.print("  logged into — LinkedIn, Twitter, paywalled news, etc.")
        if provider == "firecrawl":
            console.print("  [dim]Firecrawl can't use your logins: pages behind one go to[/]")
            console.print("  [dim]crawl4ai with this profile.[/]")
        console.print()
        existing_profiles = _list_profiles()

        table = Table(show_header=False, box=None, padding=(0, 2, 0, 4))
        table.add_column(style="bold cyan", width=3)
        table.add_column()

        opt_num = 1
        use_existing_opt = None
        if existing_profiles:
            use_existing_opt = str(opt_num)
            table.add_row(use_existing_opt, "Use an existing profile")
            opt_num += 1
        create_opt = str(opt_num)
        table.add_row(create_opt, "Create a new profile [dim]— opens browser, ~2 min[/]")
        opt_num += 1
        skip_opt = str(opt_num)
        table.add_row(skip_opt, "Skip [dim]— public pages only[/]")
        console.print(table)
        console.print()

        valid = [create_opt, skip_opt]
        if use_existing_opt:
            valid.insert(0, use_existing_opt)
        default = use_existing_opt if existing_profiles else skip_opt

        choice = Prompt.ask("  Choose", choices=valid, default=default)

        if choice == use_existing_opt and existing_profiles:
            profile = _pick_existing_profile(existing_profiles)
        elif choice == create_opt:
            profile = _create_profile_interactive()
        # else: skip, profile stays ""

    # ── Execute ───────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold]Setting up", style="green"))
    console.print()

    from hyperresearch.core.agent_docs import _resolve_executable, inject_agent_docs
    from hyperresearch.core.hooks import install_hooks
    from hyperresearch.core.vault import Vault, VaultError

    # Init vault
    try:
        vault = Vault.discover(root)
        console.print(f"  [dim]Vault:[/] {vault.root}")
    except VaultError:
        vault = Vault.init(root, name=vault_name)
        console.print(f"  [green]Vault created:[/] {vault.root}")

    # Write config — stealth always on when the local browser is used
    magic = uses_browser
    vault.config.web_provider = provider
    vault.config.web_profile = profile
    vault.config.web_magic = magic
    vault.config.name = vault_name
    vault.config.save(vault.config_path)

    # Inject CLAUDE.md
    hpr_path = _resolve_executable()
    doc_actions = inject_agent_docs(root)
    for action in doc_actions:
        console.print(f"  [green]Docs:[/] {action}")

    # Install Claude Code hook + skills + subagents (rendered from the
    # persisted scale gear, if one was chosen via `hpr profile use`)
    hook_actions = install_hooks(root, hpr_path=hpr_path, profile=vault.config.pipeline_profile)
    for action in hook_actions:
        console.print(f"  [green]Hook:[/] {action}")
    if not hook_actions:
        console.print("  [dim]Hooks already installed[/]")

    # Install browser if needed
    if uses_browser:
        _ensure_browser()

    # ── Summary ───────────────────────────────────────────────────
    console.print()
    profile_desc = profile or "none (public pages only)"

    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column(style="dim", width=12)
    summary.add_column()
    provider_desc = provider
    if provider == "firecrawl" and has_crawl4ai:
        provider_desc += " [dim](crawl4ai fallback)[/]"
    summary.add_row("Provider", f"[bold]{provider_desc}[/]")
    if provider == "firecrawl":
        summary.add_row(
            "API key",
            "[bold]FIRECRAWL_API_KEY set[/]" if _firecrawl_key_set()
            else "[yellow]not set — keyless tier[/]",
        )
    summary.add_row("Profile", f"[bold]{profile_desc}[/]")
    summary.add_row("Stealth", "[bold]on[/]" if magic else "[dim]off[/]")
    summary.add_row("Platform", "[bold]Claude Code[/]")
    summary.add_row("CLI", f"[dim]{hpr_path}[/]")

    console.print(
        Panel(
            summary,
            title="[green bold]Setup complete[/]",
            border_style="green",
            padding=(1, 2),
        )
    )
    console.print()
    console.print(f"  [dim]Start researching:[/]  {hpr_path} fetch \"https://...\" --tag topic -j")
    console.print("  [dim]Change settings:[/]    hyperresearch config show")
    console.print("  [dim]Re-run setup:[/]       hyperresearch setup")
    console.print()


# ── Helpers ─────────────────────────────────────────────────────


_PROVIDER_DESCRIPTIONS = {
    "crawl4ai": "local headless Chromium: JavaScript, stealth, login profiles. Free.",
    "firecrawl": "Firecrawl's hosted scraping and search (FIRECRAWL_API_KEY); "
    "crawl4ai takes login-walled and blocked pages",
    "builtin": "plain HTTP fetch, no browser",
}


def _provider_options(has_crawl4ai: bool, current: str | None = None) -> list[str]:
    """Providers the wizard offers, in menu order.

    A vault already on another provider (exa, tavily, ...) gets that provider
    as an extra option, so re-running setup doesn't silently replace it.
    """
    options = ["crawl4ai", "firecrawl", "builtin"] if has_crawl4ai else ["firecrawl", "builtin"]
    if current and current not in options:
        options.append(current)
    return options


def _current_provider(root: Path) -> str | None:
    """The provider of the vault setup will configure, or None for a new vault."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover(root).config.web_provider
    except VaultError:
        return None


def _choose_provider(has_crawl4ai: bool, current: str | None) -> str:
    """Step 1 menu. Defaults to the vault's current provider, else crawl4ai, else builtin."""
    options = _provider_options(has_crawl4ai, current)

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 4))
    table.add_column(style="bold cyan", width=3)
    table.add_column()
    for i, name in enumerate(options, 1):
        desc = _PROVIDER_DESCRIPTIONS.get(name, "keep the current provider")
        if name == current:
            desc += " [green](current)[/]"
        table.add_row(str(i), f"[bold]{name}[/] [dim]— {desc}[/]")
    console.print(table)
    if not has_crawl4ai:
        console.print()
        console.print("  [yellow]crawl4ai not installed[/] — no local browser, and Firecrawl has")
        console.print("  no fallback for login-walled or blocked pages.")
        console.print("  [dim]For headless browser support: pip install hyperresearch[crawl4ai][/]")
    console.print()

    first_run_default = "crawl4ai" if has_crawl4ai else "builtin"
    default = current if current in options else first_run_default
    choices = [str(i) for i in range(1, len(options) + 1)]
    choice = Prompt.ask("  Choose", choices=choices, default=str(options.index(default) + 1))
    provider = options[int(choice) - 1]

    if provider == "firecrawl":
        console.print()
        if _firecrawl_key_set():
            console.print("  [green]FIRECRAWL_API_KEY found[/]")
        else:
            console.print("  [yellow]FIRECRAWL_API_KEY not set[/] — Firecrawl's keyless tier is used:")
            console.print("  a daily per-IP cap, and batch fetches go one URL at a time.")
            console.print("  [dim]Get a key at https://firecrawl.dev and export FIRECRAWL_API_KEY[/]")
            console.print("  [dim]in the shell your agent runs in.[/]")
    return provider


def _firecrawl_key_set() -> bool:
    return bool(os.environ.get("FIRECRAWL_API_KEY", "").strip())


def _pick_existing_profile(profiles: list[str]) -> str:
    """Show a numbered list of profiles and let the user pick one."""
    console.print()
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 4))
    table.add_column(style="bold cyan", width=3)
    table.add_column()
    for i, name in enumerate(profiles, 1):
        table.add_row(str(i), name)
    console.print(table)
    console.print()

    choices = [str(i) for i in range(1, len(profiles) + 1)]
    choice = Prompt.ask("  Select profile", choices=choices, default="1")
    selected = profiles[int(choice) - 1]
    console.print(f"  [green]Using profile:[/] {selected}")
    return selected


def _list_profiles() -> list[str]:
    """List existing crawl4ai browser profiles."""
    profiles_dir = Path.home() / ".crawl4ai" / "profiles"
    if not profiles_dir.exists():
        return []
    return sorted(
        d.name for d in profiles_dir.iterdir()
        if d.is_dir() and (d / "Default").exists()
    )


def _create_profile_interactive() -> str:
    """Walk the user through creating a crawl4ai browser profile."""
    import subprocess

    profile_name = Prompt.ask("  Profile name", default="research")

    console.print()
    console.print(
        Panel(
            "[bold]A browser window will open.[/]\n\n"
            "Log in to the sites you want hyperresearch to access:\n\n"
            "  [cyan]linkedin.com[/]       profiles, posts, company pages\n"
            "  [cyan]x.com / twitter.com[/] tweets, threads, profiles\n"
            "  [cyan]reddit.com[/]         full thread content, user profiles\n"
            "  [cyan]medium.com[/]         paywalled articles\n"
            "  [cyan]news sites[/]         any paywalled publications you subscribe to\n"
            "  [cyan]github.com[/]         private repos (if needed)\n\n"
            "Take your time. Log into as many sites as you want.\n"
            "[bold]When finished, press q in the terminal to save.[/]\n\n"
            "[dim]Sessions are saved permanently. You only do this once per site.[/]",
            title="[cyan bold]Login Profile Setup[/]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    ready = Confirm.ask("  Ready to open the browser?", default=True)
    if not ready:
        console.print("  [dim]Skipped. Run 'hyperresearch setup' later to create a profile.[/]")
        return ""

    try:
        result = subprocess.run(
            [sys.executable, "-c", f"""
import asyncio
from crawl4ai import BrowserProfiler
async def main():
    profiler = BrowserProfiler()
    path = await profiler.create_profile("{profile_name}")
    print(f"PROFILE_PATH={{path}}")
asyncio.run(main())
"""],
            capture_output=False,
            timeout=600,
        )
        if result.returncode == 0:
            console.print(f"  [green]Profile '{profile_name}' saved.[/]")
            return profile_name
        else:
            console.print("  [yellow]Profile creation exited. Run 'hyperresearch setup' to retry.[/]")
            return ""
    except subprocess.TimeoutExpired:
        console.print("  [yellow]Timed out. Run 'hyperresearch setup' to try again.[/]")
        return ""
    except Exception as e:
        console.print(f"  [red]Error:[/] {e}")
        console.print("  [dim]Run 'crwl profiles' manually to create a profile.[/]")
        return ""


def _check_crawl4ai() -> bool:
    try:
        import crawl4ai  # noqa: F401
        return True
    except ImportError:
        return False


def _ensure_browser() -> None:
    """Check if Chromium is installed, install if needed.

    Checks against the stack the provider will actually launch: the stealth
    adapter uses patchright, which pins its OWN chromium build in a separate
    registry, so a passing plain-playwright check can mask a missing
    patchright browser and every fetch then dies at launch.
    """
    try:
        try:
            from patchright.sync_api import sync_playwright
        except ImportError:
            from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
        console.print("  [dim]Browser ready[/]")
    except Exception:
        console.print("  [yellow]Installing Chromium browser...[/]")
        import importlib.util
        import subprocess

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
                console.print("  [green]Chromium installed[/]")
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        else:
            console.print(
                "  [red]Could not install browser automatically.[/]\n"
                "  Run: playwright install chromium\n"
                "  (stealth adapter setups need: python -m patchright install chromium)"
            )
