from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory
from rich.panel import Panel

from ..client.stream import handle_command
from ..core.config import completer, console


def interactive_shell() -> None:
    console.print(
        Panel(
            "[bold cyan]Wolfie CLI[/bold cyan]\nConnected to daemon",
            border_style="cyan",
        )
    )

    session = PromptSession(
        history=FileHistory(".wolfie_history"),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
    )

    while True:
        try:
            text = session.prompt("wolfie ❯ ")

            if not text.strip():
                continue

            if text.lower() in {"exit", "quit"}:
                console.print("[yellow]Goodbye from Wolfie![/yellow]")
                break

            handle_command(text)
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

