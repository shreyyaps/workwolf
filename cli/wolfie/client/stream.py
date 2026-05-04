import asyncio
import json

import httpx
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from ..core.config import (
    DAEMON_AGENT_BROWSER_COMMAND_URL,
    console,
)


def _format_logs(logs: list) -> None:
    """Format and print installation logs."""
    for log in logs:
        level = log.get("level", "info")
        message = log.get("message", "")

        if level == "success":
            console.print(f"[green]{message}[/green]")
        elif level == "error":
            console.print(f"[red]{message}[/red]")
        elif level == "warning":
            console.print(f"[yellow]{message}[/yellow]")
        else:  # info
            console.print(f"[cyan]{message}[/cyan]")


def _format_response(response_text: str) -> None:
    """Format response with prettier output."""
    try:
        data = json.loads(response_text)

        # Handle logs first
        if "logs" in data:
            _format_logs(data["logs"])
            if data.get("status") != "ready":
                return

        status = data.get("status")
        message = data.get("message", "")
        reason = data.get("reason", "")

        if status == "started":
            panel_text = message if message else "Browser started successfully"
            console.print(
                Panel(
                    f"[bold green]✓ {panel_text}[/bold green]",
                    border_style="green",
                    padding=(1, 2),
                )
            )
        elif status == "ready":
            panel_text = message if message else "Ready for commands"
            console.print(
                Panel(
                    f"[bold green]✓ {panel_text}[/bold green]",
                    border_style="green",
                    padding=(1, 2),
                )
            )
        elif status == "awaiting_login":
            console.print(
                Panel(
                    f"[bold yellow]{message}[/bold yellow]",
                    border_style="yellow",
                    padding=(1, 2),
                )
            )
        elif status == "success":
            # Handle agent command success
            if data.get("data"):
                try:
                    if isinstance(data["data"], str):
                        console.print(f"[green]{data['data']}[/green]")
                    else:
                        syntax = Syntax(
                            json.dumps(data["data"], indent=2),
                            "json",
                            theme="monokai",
                            line_numbers=False,
                        )
                        console.print(syntax)
                except Exception:
                    console.print(f"[green]{data['data']}[/green]")
        elif status == "error":
            error_msg = (
                data.get("message") or data.get("error") or reason or "Unknown error"
            )
            console.print(
                Panel(
                    f"[bold red]✗ {error_msg}[/bold red]",
                    border_style="red",
                    padding=(1, 2),
                )
            )
        elif message:
            console.print(
                Panel(
                    f"[cyan]{message}[/cyan]",
                    border_style="cyan",
                    padding=(1, 2),
                )
            )
        else:
            # Fallback to syntax highlighting for JSON
            syntax = Syntax(
                json.dumps(data, indent=2),
                "json",
                theme="monokai",
                line_numbers=False,
            )
            console.print(syntax)
    except json.JSONDecodeError:
        # Not JSON, print as-is
        console.print(response_text.strip())


async def post_command(url: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            response = await client.post(url, json=payload)
            _format_response(response.text)
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")


def handle_command(text: str) -> None:
    parts = text.split()
    if not parts:
        return

    asyncio.run(
        post_command(
            DAEMON_AGENT_BROWSER_COMMAND_URL,
            {"command": " ".join(parts)},
        )
    )
