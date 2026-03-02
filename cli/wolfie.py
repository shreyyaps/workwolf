import typer
import asyncio
import subprocess
import time
import httpx

from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter

# --------------------------------------------------
# Config
# --------------------------------------------------

app = typer.Typer()
console = Console()

DAEMON_HEALTH = "http://127.0.0.1:8765/health"
DAEMON_STREAM_URL = "http://127.0.0.1:8765/run-stream"

COMMANDS = ["apply", "status", "login", "exit", "quit"]
completer = WordCompleter(COMMANDS, ignore_case=True)

# --------------------------------------------------
# Daemon management
# --------------------------------------------------


def is_daemon_running() -> bool:
    try:
        r = httpx.get(DAEMON_HEALTH, timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


def start_daemon():
    console.print("[yellow]Starting Wolfie daemon...[/yellow]")

    subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "daemon.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_daemon():
    if is_daemon_running():
        return

    start_daemon()

    # wait until daemon becomes healthy
    for _ in range(30):
        if is_daemon_running():
            console.print("[green]Wolfie daemon ready.[/green]")
            return
        time.sleep(0.5)

    console.print("[red]Failed to start daemon.[/red]")


# --------------------------------------------------
# Streaming call
# --------------------------------------------------


async def stream_command(parts: list[str]):
    output_text = Text()

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            DAEMON_STREAM_URL,
            json={"args": parts},
        ) as response:

            spinner = Spinner("dots", text=" Working...")
            with Live(spinner, console=console, refresh_per_second=12) as live:
                async for chunk in response.aiter_text():
                    spinner.text = " Receiving..."
                    output_text.append(chunk)
                    live.update(output_text)

    console.print()  # newline after stream


def handle_command(text: str):
    parts = text.split()
    asyncio.run(stream_command(parts))


# --------------------------------------------------
# Interactive shell
# --------------------------------------------------


def interactive_shell():
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


# --------------------------------------------------
# Entry point (Codex-style)
# --------------------------------------------------


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Wolfie interactive CLI."""
    if ctx.invoked_subcommand is None:
        ensure_daemon()
        interactive_shell()


if __name__ == "__main__":
    app()