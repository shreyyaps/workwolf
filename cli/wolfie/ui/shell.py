from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import NestedCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.table import Table
from rich.text import Text

from ..client.daemon import send_command
from ..core.config import console
from .theme import ACCENT, BG, DIM, FG, PROMPT_STYLE

ROOT_DIR = Path(__file__).resolve().parents[3]
HISTORY_PATH = ROOT_DIR / ".wolfie_history"
PROFILE_PATH = ROOT_DIR / "user-data"

PUBLIC_COMMAND_TREE = {
    "start": None,
    "init": None,
    "open": None,
    "prompt": None,
    "help": None,
    "clear": None,
    "exit": None,
    "quit": None,
}
COMPLETER = NestedCompleter.from_nested_dict(PUBLIC_COMMAND_TREE)


def _print_header() -> None:
    """Print the shell chrome."""
    console.print()
    console.rule("[bold cyan]WOLFIE[/bold cyan]", style=ACCENT)

    grid = Table.grid(expand=True)
    grid.style = BG
    grid.add_column(ratio=2)
    grid.add_column(ratio=1, justify="right")
    grid.add_row(
        f"[{FG}]Local browser agent bridge[/]\n"
        f"[{DIM}]Type help for commands, Tab for completion[/]",
        f"[green on grey11]daemon ready[/]\n"
        f"[{DIM}]127.0.0.1:8765[/]\n"
        f"[{DIM}]CDP 9222[/]",
    )
    console.print(grid)

    console.print()
    console.print(f"[{DIM}]quick actions[/]")
    quick = Table.grid(expand=True, padding=(0, 3))
    quick.style = BG
    quick.add_column(ratio=1)
    quick.add_column(ratio=1)
    quick.add_column(ratio=1)
    quick.add_row(
        f"[bold {ACCENT}]start[/]\n[{DIM}]Launch Chrome; prompts for Google sign-in on first use[/]",
        f"[bold {ACCENT}]init[/]\n[{DIM}]Force a re-login (clears the sign-in sentinel)[/]",
        f"[bold {ACCENT}]prompt <task>[/]\n[{DIM}]Run the LangGraph browser agent[/]",
    )
    console.print(quick)
    console.rule(style="bright_black on grey11")


def _bottom_toolbar() -> HTML:
    return HTML(
        "<bottombar>"
        "<bottombarkey> Enter </bottombarkey> send  "
        "<bottombarkey> Tab </bottombarkey> complete  "
        "<bottombarkey> help </bottombarkey> commands  "
        "<bottombarkey> clear </bottombarkey> reset"
        "</bottombar>"
    )


def _right_prompt() -> HTML:
    return HTML("<rightprompt>local only</rightprompt>")


def _print_help() -> None:
    """Print available commands."""
    table = Table(
        title="Wolfie Commands",
        show_header=True,
        header_style="bold bright_white on grey11",
        box=None,
        show_edge=False,
        padding=(0, 1),
        style=BG,
    )
    table.add_column("Scope", style=DIM, no_wrap=True)
    table.add_column("Command", style=ACCENT, no_wrap=True)
    table.add_column("What it does", style=FG)

    table.add_row("Browser", "start", "Launch Chrome with CDP; prompts for Google sign-in on first use")
    table.add_row("Browser", "init", "Force a re-login (clears the sign-in sentinel)")
    table.add_row("Browser", "open <url>", "Open a URL with the saved profile")
    table.add_row("Agent", "prompt <task>", "Run the LangGraph planner/executor browser agent")
    table.add_row("Shell", "clear", "Clear the terminal")
    table.add_row("Shell", "help", "Show this command list")
    table.add_row("Shell", "exit / quit", "Exit the CLI; daemon and Chrome keep running")

    console.print(table)
    local = Table.grid(padding=(0, 1))
    local.style = BG
    local.add_column(style=DIM, no_wrap=True)
    local.add_column()
    local.add_row("Profile", Text(str(PROFILE_PATH), style=FG))
    local.add_row("History", Text(str(HISTORY_PATH), style=FG))

    console.print()
    console.print(f"[{DIM}]local state[/]")
    console.print(local)
    console.print()


def interactive_shell() -> None:
    _print_header()

    session = PromptSession(
        history=FileHistory(str(HISTORY_PATH)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=COMPLETER,
        complete_while_typing=True,
        reserve_space_for_menu=6,
        style=PROMPT_STYLE,
    )

    while True:
        try:
            text = session.prompt(
                HTML("<prompt>wolfie</prompt> <promptarrow>></promptarrow> "),
                bottom_toolbar=_bottom_toolbar,
                rprompt=_right_prompt,
                refresh_interval=0.5,
            )

            if not text.strip():
                continue

            cmd = text.strip().lower()

            if cmd in {"exit", "quit"}:
                console.print("[yellow]Goodbye from Wolfie.[/yellow]")
                break

            if cmd == "help":
                _print_help()
                continue

            if cmd == "clear":
                console.clear()
                _print_header()
                continue

            send_command(text)
        except KeyboardInterrupt:
            console.print("[dim]Interrupted. Type exit to quit.[/dim]")
            continue
        except EOFError:
            console.print()
            break
