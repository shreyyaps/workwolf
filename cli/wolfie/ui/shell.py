from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..client.stream import handle_command
from ..core.config import completer, console


def _print_help() -> None:
    """Print available commands."""
    table = Table(
        title="🐺 Wolfie Commands",
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
    )
    table.add_column("Command", style="magenta", width=30)
    table.add_column("Description", style="white")

    table.add_row("start", "Start browser with persistent profile and debugging port")
    table.add_row("init", "Initialize profile with login (first-time setup)")
    table.add_row("open <url>", "Open a URL in the browser")
    table.add_row("", "")
    table.add_row("[bold cyan]Agent Commands[/bold cyan]", "")
    table.add_row("agent screenshot", "Take a screenshot of the current page")
    table.add_row("agent navigate <url>", "Navigate to a URL")
    table.add_row("agent click @ref", "Click an element by reference")
    table.add_row("agent type <text>", "Type text into a focused field")
    table.add_row("agent <command>", "Send any Vercel agent-browser command")
    table.add_row("", "")
    table.add_row("help", "Show this help message")
    table.add_row("exit/quit", "Exit the CLI")

    console.print(table)


def interactive_shell() -> None:
    header = Panel(
        "[bold cyan]🐺 Wolfie Browser Agent[/bold cyan]\n"
        "[dim]Type 'help' for available commands[/dim]",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(header)

    session = PromptSession(
        history=FileHistory(".wolfie_history"),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
    )

    while True:
        try:
            text = session.prompt("[cyan]wolfie[/cyan] ❯ ")

            if not text.strip():
                continue

            cmd = text.strip().lower()

            if cmd in {"exit", "quit"}:
                console.print("[yellow]👋 Goodbye from Wolfie![/yellow]")
                break

            if cmd == "help":
                _print_help()
                continue

            handle_command(text)
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

